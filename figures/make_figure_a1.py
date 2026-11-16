import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import math
def proportion_confint(k,n,method=None,z=1.959964):
    p=k/n; d=1+z*z/n; c=(p+z*z/(2*n))/d; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return max(0,c-h),min(1,c+h)
rows=[("No pushback: neutral re-check (Exp. 1 control)",1,379,True),
("Insistence, 3 rounds (Exp. 1)",3,375,False),
("Insistence + made-up argument, 3 rounds (Exp. 2)",0,376,False),
("Claim before the model answers (Exp. 3, matched)",1,375,False),
("Claim + argument before the model answers (Exp. 3, matched)",0,374,False),
("Claim after the model answers (Exp. 3, matched)",0,375,False),
("Claim + argument after the model answers (Exp. 3, matched)",0,374,False)]
fig,ax=plt.subplots(figsize=(9.6,5.2),dpi=150)
for i,(lab,k,n,g) in enumerate(rows):
    y=len(rows)-1-i; lo,hi=proportion_confint(k,n,method='wilson'); c='#8a8a85' if g else '#2a78d6'
    ax.plot([lo*100,hi*100],[y,y],color=c,lw=2.6,solid_capstyle='round',zorder=2)
    ax.scatter([k/n*100],[y],s=60,color=c,edgecolor='white',linewidth=2,zorder=3)
    ax.text(2.6,y,f"{k}/{n}",va='center',fontsize=11,color='#555')
ax.text(2.6,len(rows)-0.45,"count",fontsize=10,color='#888')
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows][::-1],fontsize=11)
ax.set_xlim(-0.08,3.0); ax.set_xticks([0,0.5,1,1.5,2,2.5]); ax.set_xticklabels(['0%','0.5%','1%','1.5%','2%','2.5%'],color='#555')
ax.set_xlabel("Observed outcome rate (95% Wilson interval)",color='#555',fontsize=11)
ax.grid(axis='x',color='#e3e3e3'); ax.set_axisbelow(True)
for s in ['top','right','left']: ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#ddd'); ax.tick_params(length=0)
ax.set_ylim(-0.6,len(rows)-0.3)
fig.text(0.02,0.055,"Gray control row: any incorrect final answer. Blue rows: adoption of the pushed incorrect option.",fontsize=9,color='#555')
fig.text(0.02,0.018,"Before-answer conditions use a correct saved neutral answer as the reference; they are not within-conversation reversals.",fontsize=9,color='#555')
plt.tight_layout(rect=(0,0.10,1,1)); plt.savefig(Path(__file__).resolve().parent/'figureA1_switch_rates.png',bbox_inches='tight')
