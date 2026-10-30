#!/usr/bin/env python3
"""Add the `-radius N` chat command (map tooling, no balance changes).

`-radius 400` draws a hollow green ring of radius 400 (WC3 units) around the
typing player's hero (udg_PlayerHero[pid]); it follows the hero every 0.04 s.
Only that player sees it. A new `-radius N` replaces the old ring (one ring per
player). `-radius 0` / `-radius off` removes it. Players 1-3 (Player(0..2)).

Ring = 36 lightning segments (AddLightningEx, codename CLSB) created for every
client, tinted green with alpha 1 only on the owner's client
(GetLocalPlayer()==p), alpha 0 elsewhere. No handle is created/destroyed inside
a GetLocalPlayer block -> sync-safe.

Idempotent (marker `// PATCH: radius-command`).

usage: patch_radius_command.py [<in.j> <out.j>]
  no args -> patches maps/patched/war3map.j and maps/patched/war3map_all_pick_v2.j in place
"""
import sys, os

MARK = '// PATCH: radius-command'
SEG = 36

GLOBALS = f'''{MARK}
lightning array RC_L
real array RC_R
real array RC_PX
real array RC_PY
location RC_Loc=null
timer RC_T=null
trigger gg_trg_Radius_Cmd=null'''

FUNCS = f'''{MARK}
function RC_Clear takes integer pid returns nothing
local integer i=0
loop
exitwhen i>={SEG}
if RC_L[pid*{SEG}+i]!=null then
call DestroyLightning(RC_L[pid*{SEG}+i])
set RC_L[pid*{SEG}+i]=null
endif
set i=i+1
endloop
set RC_R[pid]=0.
endfunction
function RC_Update takes integer pid returns nothing
local unit u=udg_PlayerHero[pid]
local real r=RC_R[pid]
local real x
local real y
local real a=0.
local real z1
local real z2
local integer i=0
local lightning l
if r<=0. then
set u=null
return
endif
if GetLocalPlayer()==Player(pid-1) then
set a=1.
endif
if u==null or GetUnitTypeId(u)==0 then
loop
exitwhen i>={SEG}
call SetLightningColor(RC_L[pid*{SEG}+i],0.,1.,0.,0.)
set i=i+1
endloop
set u=null
return
endif
set x=GetUnitX(u)
set y=GetUnitY(u)
loop
exitwhen i>{SEG}
set RC_PX[i]=x+r*Cos(i*2.*bj_PI/{SEG})
set RC_PY[i]=y+r*Sin(i*2.*bj_PI/{SEG})
set i=i+1
endloop
set i=0
call MoveLocation(RC_Loc,RC_PX[0],RC_PY[0])
set z1=GetLocationZ(RC_Loc)+10.
loop
exitwhen i>={SEG}
call MoveLocation(RC_Loc,RC_PX[i+1],RC_PY[i+1])
set z2=GetLocationZ(RC_Loc)+10.
set l=RC_L[pid*{SEG}+i]
call MoveLightningEx(l,false,RC_PX[i],RC_PY[i],z1,RC_PX[i+1],RC_PY[i+1],z2)
call SetLightningColor(l,0.,1.,0.,a)
set z1=z2
set i=i+1
endloop
set l=null
set u=null
endfunction
function RC_Tick takes nothing returns nothing
local integer pid=1
loop
exitwhen pid>3
if RC_R[pid]>0. then
call RC_Update(pid)
endif
set pid=pid+1
endloop
endfunction
function RC_IsNum takes string s returns boolean
local integer i=0
local integer n=StringLength(s)
local integer dots=0
local string c
if n==0 or n>8 then
return false
endif
loop
exitwhen i>=n
set c=SubString(s,i,i+1)
if c=="." then
set dots=dots+1
elseif c!="0" and c!="1" and c!="2" and c!="3" and c!="4" and c!="5" and c!="6" and c!="7" and c!="8" and c!="9" then
return false
endif
set i=i+1
endloop
return dots<=1 and n>dots
endfunction
function Trig_Radius_Cmd_Actions takes nothing returns nothing
local player p=GetTriggerPlayer()
local integer pid=GetPlayerId(p)+1
local string s=GetEventPlayerChatString()
local integer n=StringLength(s)
local integer b
local integer e
local string arg
local real r
local integer i=0
if pid<1 or pid>3 or SubString(s,0,7)!="-radius" then
set p=null
return
endif
if n>7 and SubString(s,7,8)!=" " then
set p=null
return
endif
set b=7
loop
exitwhen b>=n or SubString(s,b,b+1)!=" "
set b=b+1
endloop
set e=n
loop
exitwhen e<=b or SubString(s,e-1,e)!=" "
set e=e-1
endloop
set arg=StringCase(SubString(s,b,e),false)
if arg=="off" then
call RC_Clear(pid)
call DisplayTextToPlayer(p,0,0,"Radius: off")
set p=null
return
endif
if not RC_IsNum(arg) then
set p=null
return
endif
set r=S2R(arg)
call RC_Clear(pid)
if r<=0. then
call DisplayTextToPlayer(p,0,0,"Radius: off")
set p=null
return
endif
loop
exitwhen i>={SEG}
set RC_L[pid*{SEG}+i]=AddLightningEx("CLSB",false,0.,0.,0.,0.,0.,0.)
call SetLightningColor(RC_L[pid*{SEG}+i],0.,1.,0.,0.)
set i=i+1
endloop
set RC_R[pid]=r
call RC_Update(pid)
call DisplayTextToPlayer(p,0,0,"Radius: "+R2SW(r,1,0))
set p=null
endfunction
function InitTrig_Radius_Cmd takes nothing returns nothing
set gg_trg_Radius_Cmd=CreateTrigger()
call TriggerRegisterPlayerChatEvent(gg_trg_Radius_Cmd,Player(0),"-radius",false)
call TriggerRegisterPlayerChatEvent(gg_trg_Radius_Cmd,Player(1),"-radius",false)
call TriggerRegisterPlayerChatEvent(gg_trg_Radius_Cmd,Player(2),"-radius",false)
call TriggerAddAction(gg_trg_Radius_Cmd,function Trig_Radius_Cmd_Actions)
set RC_Loc=Location(0.,0.)
set RC_T=CreateTimer()
call TimerStart(RC_T,0.04,true,function RC_Tick)
endfunction'''


def patch(text):
    nl = '\r\n' if '\r\n' in text else '\n'
    if MARK in text:
        return text, False
    lines = text.split(nl)
    eg = lines.index('endglobals')
    lines[eg:eg] = GLOBALS.split('\n')
    # after InitTrig_Clear's endfunction
    i = lines.index('function InitTrig_Clear takes nothing returns nothing')
    while lines[i] != 'endfunction':
        i += 1
    lines[i + 1:i + 1] = FUNCS.split('\n')
    j = lines.index('call InitTrig_Clear()')
    lines.insert(j + 1, 'call InitTrig_Radius_Cmd()')
    return nl.join(lines), True


def run(src, dst):
    text = open(src, encoding='latin-1', newline='').read()
    out, changed = patch(text)
    assert out.count(MARK) == 2 and out.count('call InitTrig_Radius_Cmd()') == 1
    if changed or src != dst:
        open(dst, 'w', encoding='latin-1', newline='').write(out)
    print(f'radius-command: {"patched" if changed else "already patched (no-op)"} -> {dst}')


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        run(sys.argv[1], sys.argv[2])
    else:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'maps', 'patched')
        for f in ('war3map.j', 'war3map_all_pick_v2.j'):
            p = os.path.join(root, f)
            run(p, p)
