export function readController(pad, config={}) {
  if(!pad?.connected) throw new Error('Controller disconnected');
  const raw=config.stick==='raw',right=config.stick==='right';
  if(!raw&&pad.mapping!=='standard') throw new Error('Choose raw mapping for an unmapped controller');
  const ti=raw?config.throttleAxis:right?3:1,si=raw?config.steeringAxis:right?2:0,bi=raw?config.holdButton:4;
  if(![ti,si,bi].every(Number.isInteger)||Math.min(ti,si,bi)<0||ti>=pad.axes.length||si>=pad.axes.length||bi>=pad.buttons.length)throw new Error('Mapping exceeds controller axes/buttons');
  const throttle=-pad.axes[ti],steering=pad.axes[si];
  if(![throttle,steering].every(v=>Number.isFinite(v)&&Math.abs(v)<=1))throw new Error('Invalid controller axis');
  return {throttle,steering,deadman:!!pad.buttons[bi].pressed};
}
