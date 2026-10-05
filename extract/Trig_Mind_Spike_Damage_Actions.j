function Trig_Mind_Spike_Damage_Actions takes nothing returns nothing
set udg_DCS_Unit=udg_Hero_Priest
set udg_DCS_IncludeAttributeBonus=true
set udg_DCS_IncludeItemBonus=true
call TriggerExecute(gg_trg_DCS_Core)
call TriggerExecute(gg_trg_DCS_Other_Damage_Sources)
set udg_MindSpike_Damage=((40.00+(40.00*I2R(GetUnitAbilityLevelSwapped('A0GB',udg_Hero_Priest))))+(1.50*I2R(GetHeroStatBJ(bj_HEROSTAT_INT,udg_Hero_Priest,true))))
set udg_MindSpike_Damage=(udg_MindSpike_Damage*(1+(0.01*udg_DCS_Damage)))
if(Trig_Mind_Spike_Damage_Func010C())then
set udg_MindSpike_Damage=(udg_MindSpike_Damage*(1+(0.10*I2R(udg_DarkEvangelism_Charges))))
set udg_DarkEvangelism_Charges=0
call FlushChildHashtable(TasAbilityChargeBox_Hash,GetHandleId((udg_Hero_Priest)))
else
endif
if(Trig_Mind_Spike_Damage_Func011C())then
set udg_MindSpike_Damage=(udg_MindSpike_Damage*1.25)
else
endif
set udg_NextDamageType=udg_DamageTypeMagical
call UnitDamageTargetBJ(udg_Hero_Priest,udg_MindSpike_Target,udg_MindSpike_Damage,ATTACK_TYPE_NORMAL,DAMAGE_TYPE_NORMAL)
call AddSpecialEffectTargetUnitBJ("origin",udg_MindSpike_Target,"war3mapImported\\doombolttarget.mdx")
call DestroyEffectBJ(GetLastCreatedEffectBJ())
if(Trig_Mind_Spike_Damage_Func017C())then
set udg_CC_Duration=1.50
call SetUnitManaBJ(udg_MindSpike_Target,(GetUnitStateSwap(UNIT_STATE_MANA,udg_MindSpike_Target)-((10.00+(5.00*I2R(GetUnitAbilityLevelSwapped('A0GB',udg_Hero_Priest))))+(0.04*GetUnitStateSwap(UNIT_STATE_MAX_MANA,udg_Hero_Priest)))))
else
set udg_CC_Duration=0.50
endif
set udg_CC_Target=udg_MindSpike_Target
set udg_CC_Hero=udg_Hero_Priest
call TriggerExecute(gg_trg_Stun)
if(Trig_Mind_Spike_Damage_Func022C())then
set udg_ShadowWord_Target=udg_MindSpike_Target
call ConditionalTriggerExecute(gg_trg_Shadow_Word_Pain_Apply)
else
endif
if(Trig_Mind_Spike_Damage_Func023C())then
call TriggerExecute(gg_trg_Divine_Image_Resonate)
else
endif
endfunction
