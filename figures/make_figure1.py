import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
rows=[("Flawed",15,25,0,40),("Middling",13,24,3,40),("Strong",3,31,5,39),
      ("Flawed",17,23,0,40),("Middling",20,20,0,40),("Strong",9,30,0,39)]
groups=["“I wrote this and I'm proud of it”  vs.  neutral","“I really like it”  vs.  “I really don't like it”"]
fig,ax=plt.subplots(figsize=(9.6,4.9),dpi=150)
BLUE,ORANGE='#2a78d6','#d9822b'
ys=[7,6,5,2.6,1.6,0.6]
for (lab,up,same,down,n),y in zip(rows,ys):
    ax.barh(y,up,height=0.62,color=BLUE,left=0,zorder=3)
    ax.barh(y,-down,height=0.62,color=ORANGE,left=0,zorder=3)
    ax.text(-27,y,lab,va='center',ha='left',fontsize=11)
    ax.text(up+0.6 if up else 0.6,y,f"{up} higher",va='center',fontsize=10,color='#333')
    if down: ax.text(-down-0.6,y,f"{down} lower",va='center',ha='right',fontsize=10,color='#333')
    ax.text(30.5,y,f"{same} of {n} unchanged",va='center',ha='left',fontsize=10,color='#666')
ax.text(-27,7.75,groups[0],fontsize=11,fontweight='bold')
ax.text(-27,3.35,groups[1],fontsize=11,fontweight='bold')
ax.axvline(0,color='#999',lw=1,zorder=2)
ax.set_xlim(-27,40); ax.set_ylim(0,8.2)
ax.set_xticks([-10,-5,0,5,10,15,20]); ax.set_xticklabels(['10','5','0','5','10','15','20'],color='#555')
ax.set_yticks([])
for s in ['top','right','left']: ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#ccc'); ax.tick_params(length=0)
ax.grid(axis='x',color='#eee',zorder=0)
ax.set_xlabel("Matched model-essay pairs:  scored lower  ←  |  →  scored higher  (same essay, same model)",color='#555',fontsize=10)
plt.tight_layout(); plt.savefig(Path(__file__).resolve().parent/'figure1_feedback_shifts.png',bbox_inches='tight')
