function Trig_Shadow_Word_Pain_Apply_Actions takes nothing returns nothing
if(Trig_Shadow_Word_Pain_Apply_Func001C())then
set udg_ShadowWord_InstantDmg=(75.00+(1.50*I2R(GetHeroStatBJ(bj_HEROSTAT_INT,udg_Hero_Priest,true))))
if(Trig_Shadow_Word_Pain_Apply_Func001Func002C())then
set udg_ShadowWord_InstantDmg=(udg_ShadowWord_InstantDmg*(1.00+(0.10+((0.06/ 10.00)*I2R(udg_Mastery_Stat[GetConvertedPlayerId(GetOwningPlayer(udg_Hero_Priest))])))))
else
endif
set udg_NextDamageType=udg_DamageTypeMagical
call UnitDamageTargetBJ(udg_Hero_Priest,udg_ShadowWord_Target,udg_ShadowWord_InstantDmg,ATTACK_TYPE_NORMAL,DAMAGE_TYPE_NORMAL)
call AddSpecialEffectTargetUnitBJ("origin",udg_ShadowWord_Target,"war3mapImported\\ShadowBlast.mdx")
call DestroyEffectBJ(GetLastCreatedEffectBJ())
else
endif
call UnitAddAbilityBJ('A0GL',udg_Caster_Dummy)
if(Trig_Shadow_Word_Pain_Apply_Func003C())then
call SetUnitAbilityLevelSwapped('A0GL',udg_Caster_Dummy,2)
else
endif
call IssueTargetOrderBJ(udg_Caster_Dummy,"curse",udg_ShadowWord_Target)
call UnitRemoveAbilityBJ('A0GL',udg_Caster_Dummy)
endfunction
