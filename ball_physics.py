"""Deterministic ball motion in Qt's logical screen coordinates (no UI dependency)."""
from dataclasses import dataclass
import math


@dataclass
class BallMotion:
    x: float = 0
    y: float = 0
    vx: float = 0
    vy: float = 0
    radius: float = 16
    gravity: float = 1300
    restitution: float = .52
    grounded: bool = False
    head_contacted: bool = False

    def release(self,x,y):
        self.x,self.y=x,y; self.vx=self.vy=0
        self.grounded=False; self.head_contacted=False

    def advance(self,seconds,bounds,head=None,on_head=None):
        if seconds<=0: return
        left,top,right,bottom=bounds
        left+=self.radius+2; right=max(left,right-self.radius-2)
        top+=self.radius+2; floor=max(top,bottom-self.radius-2)
        count=max(1,math.ceil(seconds*240)); dt=seconds/count
        for _ in range(count):
            old_x,old_y=self.x,self.y
            self.x+=self.vx*dt
            if not self.grounded or self.y<floor-.01:
                self.grounded=False
                self.y+=self.vy*dt+.5*self.gravity*dt*dt
                self.vy+=self.gravity*dt
            if head and on_head and not self.head_contacted and self.vy>0:
                hl,hy,hr=head
                if old_y+self.radius<=hy and self.y+self.radius>=hy:
                    fraction=(hy-self.radius-old_y)/max(1e-9,self.y-old_y)
                    contact_x=old_x+(self.x-old_x)*fraction
                    if hl-self.radius*.6<=contact_x<=hr+self.radius*.6:
                        velocity=on_head(contact_x,hy-self.radius,floor)
                        if velocity is not None:
                            self.x,self.y=contact_x,hy-self.radius-.5
                            self.vx,self.vy=velocity
                            self.head_contacted=True; self.grounded=False
            if self.x<left:
                self.x=left; self.vx=abs(self.vx)*.62
            elif self.x>right:
                self.x=right; self.vx=-abs(self.vx)*.62
            if self.y<top:
                self.y=top; self.vy=abs(self.vy)*.5
            if self.y>=floor:
                self.y=floor
                if self.vy>0:
                    self.vy=-self.vy*self.restitution; self.vx*=.75
                    if abs(self.vy)<45: self.vy=0; self.grounded=True
                elif self.grounded: self.vy=0
            if self.grounded:
                self.vx*=math.exp(-4.5*dt)
                if abs(self.vx)<3: self.vx=0

    def head_launch(self,x,y,floor,direction,distance,height):
        """Choose finite horizontal travel over the initial flight and damped bounces."""
        vy=-math.sqrt(2*self.gravity*height)
        impact=math.sqrt(vy*vy+2*self.gravity*max(0,floor-y))
        first=(-vy+impact)/self.gravity
        ratio=self.restitution*.75
        tail=2*impact/self.gravity*ratio/(1-ratio)
        return direction*distance/max(.1,first+tail),vy
