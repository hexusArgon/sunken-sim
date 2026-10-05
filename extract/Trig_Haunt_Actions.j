function Trig_Haunt_Actions takes nothing returns nothing
set udg_Haunt_Target=GetSpellTargetUnit()
call TriggerExecute(gg_trg_Haunt_Apply)
endfunction
