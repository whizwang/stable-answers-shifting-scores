"""Offline replay of all saved FlipRate records and preserved runner snapshots.

No model requests are made. A fake client checks model IDs and full message
roles/content before returning the next saved reply. It checks every stored
record field, including follow-up scores and finish reasons where recorded.
No-transcript timing records are exercised rather than skipped. Constructed
HTTP payloads are checked with a fake transport; this validates current code,
not historical provider-side settings or missing source provenance.
"""
from pathlib import Path
import argparse, collections, importlib.util, json, sys, urllib.request, socket
import contextlib, csv, io, shutil, tempfile


def blocked_network(*args, **kwargs):
    raise AssertionError("Network access is disabled during offline replay")


class ReplayClient:
    def __init__(self, module, record):
        self.module = module
        self.record = record
        self.saved = record.get("messages", [])
        self.finishes = record.get("finish_reasons", [record.get("finish_reason")])
        self.calls = 0
        self.returned_positions = []

    def chat(self, model, messages):
        if model != self.record["model"]:
            raise AssertionError("model argument differs from saved record")
        n = len(messages)
        if messages != self.saved[:n]:
            raise AssertionError("message history differs (role/content)")
        if n >= len(self.saved) or self.saved[n].get("role") != "assistant":
            raise AssertionError("runner requested a reply absent from saved transcript")
        if self.returned_positions and n <= self.returned_positions[-1]:
            raise AssertionError("runner requested an earlier reply twice")
        self.returned_positions.append(n)
        text = self.saved[n]["content"]
        reply = self.module.Reply(text) if hasattr(self.module, "Reply") else text
        if hasattr(reply, "finish"):
            reply.finish = self.finishes[self.calls] if self.calls < len(self.finishes) else None
        self.calls += 1
        return reply


def load_module(path, data_dir, index):
    spec = importlib.util.spec_from_file_location(f"fliprate_replay_{index}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Snapshots sit in script_versions/ but all use the same supplied materials.
    module.HERE = str(data_dir)
    module.QUESTIONS_CSV = str(data_dir / "questions.csv")
    module.RESULTS = str(data_dir / "results.jsonl")
    return module


def replay_records(module, records, experiment):
    questions = {q["id"]: q for q in module.load_questions()}
    arguments = module.load_arguments() if experiment in (2, 3) else None
    saved = module.load_saved_answers() if experiment == 3 else None
    essays = {e["essay_id"]: e for e in module.load_essays()} if experiment == 4 else None
    result = {"records": len(records), "tested": 0, "skipped": 0,
              "with_transcripts": 0, "without_transcripts": 0,
              "fake_chat_calls": 0, "mismatches": []}
    for record in records:
        client = ReplayClient(module, record)
        identity = {k: record[k] for k in ("model", "id", "essay_id", "condition", "framing") if k in record}
        try:
            if experiment in (1, 2):
                kwargs = {"arguments": arguments} if experiment == 2 else {}
                replay = module.run_one(client, record["model"], questions[record["id"]], record["condition"], **kwargs)
            elif experiment == 3:
                replay = module.run_timing_one(client, record["model"], questions[record["id"]], record["condition"], arguments, saved)
            else:
                replay = module.run_feedback_one(client, record["model"], essays[record["essay_id"]], record["framing"])
            # Every field that was actually saved must agree. Later versions may
            # add fields (e.g. finish_reasons) absent from the original schema.
            differences = [k for k in record if k not in replay or record[k] != replay[k]]
            if differences:
                raise AssertionError("stored fields differ: " + ", ".join(differences))
            expected_calls = (len(record.get("messages", [])) // 2 if experiment in (1, 2)
                              else int(bool(record.get("messages"))))
            if client.calls != expected_calls:
                raise AssertionError(f"fake client calls {client.calls}, expected {expected_calls}")
            if record.get("messages") and client.returned_positions[-1] != len(record["messages"]) - 1:
                raise AssertionError("runner did not consume the final saved reply")
        except Exception as error:
            result["mismatches"].append({**identity, "error": str(error)})
        result["tested"] += 1
        result["with_transcripts" if record.get("messages") else "without_transcripts"] += 1
        result["fake_chat_calls"] += client.calls
    return result


class FakeHTTPResponse:
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self):
        return json.dumps({"choices": [{"message": {"content": "ANSWER: A\nCONFIDENCE: 100"},
                                        "finish_reason": "stop"}], "usage": {"total_tokens": 1}}).encode()


def inspect_http_payloads(module):
    payloads = []
    def fake_urlopen(request, timeout=None):
        if request.full_url != "https://openrouter.ai/api/v1/chat/completions":
            raise AssertionError("unexpected request URL")
        payloads.append(json.loads(request.data.decode()))
        return FakeHTTPResponse()
    profiles = [("default", None)]
    if hasattr(module, "run_feedback"):
        profiles.append(("feedback", getattr(module, "FEEDBACK_MAX_TOKENS", module.MAX_TOKENS)))
    if hasattr(module, "ARG_MAX_TOKENS"):
        profiles.append(("argument_generation", module.ARG_MAX_TOKENS))
    rows = []
    urllib.request.urlopen = fake_urlopen
    try:
        for label, tokens in profiles:
            for model in module.MODELS:
                kwargs = {} if tokens is None else {"max_tokens": tokens}
                client = module.OpenRouter("OFFLINE_TEST_PLACEHOLDER", **kwargs)
                messages = [{"role": "user", "content": "Offline payload probe"}]
                client.chat(model, messages)
                actual = payloads[-1]
                expected = {"model": model, "messages": messages,
                            "max_tokens": module.MAX_TOKENS if tokens is None else tokens,
                            "temperature": module.TEMPERATURE}
                if actual != expected:
                    raise AssertionError("constructed request payload differs from declared settings")
                rows.append({"profile": label, "model": model,
                             "max_tokens": actual["max_tokens"], "temperature": actual["temperature"],
                             "system_message": any(m["role"] == "system" for m in actual["messages"])})
    finally:
        urllib.request.urlopen = blocked_network
    return rows


def check_empty_argument_rewrite(module, data_dir, expect_rewrite):
    """Controlled fixture, not a replay of a saved generation API transcript.

    In a temporary copy, make the known failed argument empty, then provide
    its already saved replacement as a canned reply. Original data stay intact.
    """
    with (data_dir / "arguments.csv").open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        original = list(reader)
    key = ("high_school_mathematics-4", "D")
    source = next(r for r in original if (r["id"], r["letter"]) == key)
    if not source["argument"].strip():
        raise AssertionError("controlled fixture requires the saved replacement argument")
    fixture = [dict(r) for r in original]
    for row in fixture:
        if (row["id"], row["letter"]) == key:
            row["argument"] = ""
            row["finish"] = "length"
    calls, budgets = [], []
    with tempfile.TemporaryDirectory(prefix="fliprate-rewrite-probe-") as tmp:
        target_dir = Path(tmp)
        shutil.copyfile(data_dir / "questions.csv", target_dir / "questions.csv")
        with (target_dir / "arguments.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(fixture)
        prior = {k: getattr(module, k) for k in ("HERE", "QUESTIONS_CSV", "OpenRouter", "find_arg_model", "load_key")}
        module.HERE = str(target_dir)
        module.QUESTIONS_CSV = str(target_dir / "questions.csv")
        question = next(q for q in module.load_questions() if q["id"] == key[0])
        expected_prompt = module.ARG_PROMPT.format(
            letter=key[1], question=question["question"],
            choices=module.fmt_choices([question[x] for x in "ABCD"]))

        class FakeArgumentClient:
            def __init__(self, key_placeholder, max_tokens=None):
                budgets.append(max_tokens)

            def chat(self, model, messages):
                if model != source["writer"]:
                    raise AssertionError("generation fixture model differs")
                if messages != [{"role": "user", "content": expected_prompt}]:
                    raise AssertionError("generation fixture prompt differs")
                calls.append(model)
                reply = module.Reply(source["argument"])
                reply.finish = "stop"
                return reply

        module.OpenRouter = FakeArgumentClient
        module.find_arg_model = lambda: source["writer"]
        module.load_key = lambda: "OFFLINE_TEST_PLACEHOLDER"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                module.make_arguments()
            with (target_dir / "arguments.csv").open(encoding="utf-8", newline="") as f:
                after = list(csv.DictReader(f))
        finally:
            for name, value in prior.items():
                setattr(module, name, value)
    before_map = {(r["id"], r["letter"]): r for r in fixture}
    after_map = {(r["id"], r["letter"]): r for r in after}
    other_unchanged = all(after_map[k] == r for k, r in before_map.items() if k != key)
    expected_text = source["argument"] if expect_rewrite else ""
    if len(after) != len(original) or not other_unchanged or after_map[key]["argument"] != expected_text:
        raise AssertionError("empty-argument rewrite fixture differs from expected behavior")
    if len(calls) != int(expect_rewrite) or budgets != [module.ARG_MAX_TOKENS]:
        raise AssertionError("unexpected generation fixture calls or token budget")
    return {"scope": "controlled empty-row fixture, no historical generator transcript asserted",
            "argument": list(key), "expected_rewrite": expect_rewrite,
            "fake_generation_calls": len(calls), "configured_generation_max_tokens": budgets[0],
            "other_rows_unchanged": other_unchanged, "output_rows": len(after), "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    sys.dont_write_bytecode = True
    urllib.request.urlopen = blocked_network
    socket.create_connection = blocked_network
    socket.socket.connect = blocked_network
    sources = [("Exp1 preserved", data_dir / "script_versions/fliprate_used_for_exp1.py", [1]),
               ("First-argument-pass recovered (compatibility check)", data_dir / "script_versions/fliprate_used_for_first_argument_pass.py", [1, 2]),
               ("Exp2 recovered", data_dir / "script_versions/fliprate_used_for_exp2.py", [1, 2]),
               ("Exp3 preserved", data_dir / "script_versions/fliprate_used_for_exp3.py", [1, 2, 3]),
               ("First-essay preserved", data_dir / "script_versions/fliprate_used_for_exp4_first_essays.py", [1, 2, 3]),
               ("Final", data_dir / "fliprate.py", [1, 2, 3, 4])]
    names = {1: "results.jsonl", 2: "results_argument.jsonl", 3: "results_timing.jsonl", 4: "results_feedback.jsonl"}
    records = {e: [json.loads(line) for line in (data_dir / name).read_text().splitlines() if line.strip()] for e, name in names.items()}
    output = {"scope": "Offline saved-transcript replay plus constructed-request inspection; not proof of historical runtime settings or source provenance.",
              "runner_versions": []}
    failures = 0
    for index, (label, path, experiments) in enumerate(sources):
        module = load_module(path, data_dir, index)
        item = {"label": label, "file": str(path.relative_to(data_dir)),
                "request_profiles": inspect_http_payloads(module), "experiments": {}}
        for experiment in experiments:
            result = replay_records(module, records[experiment], experiment)
            item["experiments"][str(experiment)] = result
            failures += len(result["mismatches"])
            print(f"{label}, Exp {experiment}: {result['tested']}/{result['records']} tested, {result['without_transcripts']} without transcripts, {len(result['mismatches'])} mismatches")
        if path.name in ("fliprate_used_for_first_argument_pass.py", "fliprate_used_for_exp2.py"):
            item["empty_argument_rewrite_fixture"] = check_empty_argument_rewrite(
                module, data_dir, expect_rewrite=path.name == "fliprate_used_for_exp2.py")
            fixture = item["empty_argument_rewrite_fixture"]
            print(f"{label}, controlled generation fixture: {fixture['fake_generation_calls']} fake calls, {fixture['configured_generation_max_tokens']} tokens, passed")
        output["runner_versions"].append(item)
    output["total_record_version_checks"] = sum(r["tested"] for v in output["runner_versions"] for r in v["experiments"].values())
    output["total_mismatches"] = failures
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(f"All checks complete; {failures} mismatches; no model/network calls.")
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
