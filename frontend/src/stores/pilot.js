import {pilot} from '../api/pilot.js';
export const pilotStore={plans:[],planId:0,detail:null,error:''};
export async function loadPlans(){const data=await pilot.plans();pilotStore.plans=data.plans;if(!pilotStore.planId)pilotStore.planId=pilotStore.plans[0]?.id||0;}
export async function loadDetail(id){pilotStore.planId=id||pilotStore.planId;if(!pilotStore.planId){pilotStore.detail=null;return null;}pilotStore.detail=await pilot.plan(pilotStore.planId);return pilotStore.detail;}
export const writable=()=>localStorage.getItem('research-role')!=='viewer';
