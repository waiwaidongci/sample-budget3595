import {request,post} from './client.js';
export const pilot={
  plans:()=>request('/pilot/plans'),
  createPlan:x=>post('/pilot/plans',x),
  plan:id=>request(`/pilot/plans/${id}`),
  daily:(id,x)=>post(`/pilot/plans/${id}/daily`,x),
  removeDaily:(id,row)=>request(`/pilot/plans/${id}/daily/${row}`,{method:'DELETE'}),
  seal:id=>post(`/pilot/plans/${id}/seal`,{}),
  spillover:(id,x)=>post(`/pilot/plans/${id}/spillovers`,x),
  run:(id,x)=>post(`/pilot/plans/${id}/runs`,x),
  current:id=>request(`/pilot/plans/${id}/current`),
  getRun:id=>request(`/pilot/runs/${id}`),
  exportRun:id=>request(`/pilot/runs/${id}/export`)
};
