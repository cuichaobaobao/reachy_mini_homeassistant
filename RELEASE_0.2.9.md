## Changes

Manual controls now follow the desktop controller:

- Values outside a range are clamped into the desktop ranges instead of rejected.
- The 65° head/body yaw limit is left to the daemon's automatic body yaw, as on the desktop. Turning the head far may turn the body a little; turning the body far with Head follows body off may stop short.
- A movement continues from the last target HA sent. Only a larger difference (the desktop's 0.1 major-change threshold) means the robot was moved elsewhere, and then the measured pose is used. Small measurement offsets no longer leak into the next movement.
- Head X, Head pitch and Head yaw use the desktop's display signs: positive is forward, up and right. Automations that set these three values need the opposite sign.
- Manual control values are shown with three decimals, like the desktop.

Head follows body, Center head, Center body and Movement duration are unchanged.

## Impact

Only manual-control target calculation and number display change. Other entities, polling, camera code, media dependencies and icons are unchanged.

## Notes

Update through HACS and restart Home Assistant. Please check on the robot that dragging Head yaw to the right turns the head right.
