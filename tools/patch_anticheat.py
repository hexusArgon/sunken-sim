#!/usr/bin/env python3
"""Neutralize Sunken City's built-in cheat punishment ("Execute").

Why: five detector triggers (Synergy_Disable, Greed_Is_Not_Good,
Greed_Is_Not_Good_2, I_am_your_daddy, I_see_dead_players) react to
iseedeadpeople / whosyourdaddy / greedisgood (and, in All Pick, to a second
hero of the same player entering the map) by setting team lives to 1 and
enabling gg_trg_Execute, which every second kills all heroes and locks the
camera -> instant defeat, the game ends ("crash").

What: removes the punishment lines from the detectors and turns
Trig_Execute_Actions into a self-disabling no-op. Idempotent.

usage: patch_anticheat.py <in war3map.j> <out war3map.j>
"""
import sys

DETECTORS = ['Trig_Synergy_Disable_Actions', 'Trig_Greed_Is_Not_Good_Actions',
             'Trig_Greed_Is_Not_Good_2_Actions', 'Trig_I_am_your_daddy_Actions',
             'Trig_I_see_dead_players_Actions']
PUNISH = ('set udg_PlayerTeam_Lives=1',
          'call MultiboardSetItemValueBJ(udg_Main_Board,3,1,("Lives: "+I2S(udg_PlayerTeam_Lives)))',
          'call EnableTrigger(gg_trg_Execute)')


def patch(lines):
    out, cur, removed, execd = [], None, 0, False
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith('function '):
            cur = l.split()[1]
            if cur == 'Trig_Execute_Actions':
                out.append(l)
                out.append('call DisableTrigger(GetTriggeringTrigger())')
                while lines[i] != 'endfunction':
                    i += 1
                out.append('endfunction')
                execd = True
                i += 1
                continue
        elif l == 'endfunction':
            cur = None
        if cur in DETECTORS and l in PUNISH:
            removed += 1
            i += 1
            continue
        out.append(l)
        i += 1
    if not execd:
        raise SystemExit('Trig_Execute_Actions not found')
    return out, removed


def main(src, dst):
    text = open(src, encoding='latin-1', newline='').read()
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(nl)
    out, removed = patch(lines)
    assert 'call EnableTrigger(gg_trg_Execute)' not in out
    open(dst, 'w', encoding='latin-1', newline='').write(nl.join(out))
    print(f'anticheat: removed {removed} punishment lines, Execute neutralized -> {dst}')


if __name__ == '__main__':
    main(*sys.argv[1:3])
