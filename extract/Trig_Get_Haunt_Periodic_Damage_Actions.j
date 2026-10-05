function Trig_Get_Haunt_Periodic_Damage_Actions takes nothing returns nothing
set udg_Haunt_Damage=((10.00*I2R(GetUnitAbilityLevelSwapped('A0QW',udg_Hero_Warlock)))+(0.15*I2R(GetHeroStatBJ(bj_HEROSTAT_INT,udg_Hero_Warlock,true))))
if(Trig_Get_Haunt_Periodic_Damage_Func002C())then
set udg_DCS_Unit=udg_Hero_Warlock
set udg_DCS_IncludeAttributeBonus=true
set udg_DCS_IncludeItemBonus=true
call TriggerExecute(gg_trg_DCS_Core)
call TriggerExecute(gg_trg_DCS_Other_Damage_Sources)
set udg_Haunt_Damage=(udg_Haunt_Damage+(0.10*udg_DCS_Damage))
else
endif
endfunction
