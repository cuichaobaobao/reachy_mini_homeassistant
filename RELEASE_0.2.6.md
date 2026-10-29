## Changes

- Add manual head, body and antenna controls, center buttons and movement duration.
- Add Head follows body. Turning the body can preserve the head's relative pose.
- Add Power Off. A configured Startup app keeps the backend available for antenna wake; otherwise the backend stops.

## Impact

Manual controls send commands directly to the robot when the cached state is ready and no app is active. There are no app/slot/motor preflight requests before each movement. Normal polling now also reads the current app, pose and running moves.

Camera code, media dependencies, icons and existing app controls are unchanged. No voice-app or daemon update is included.

## Notes

Update through HACS and restart Home Assistant. Test small movements first. Cloud tests do not replace testing on the robot.

Power Off is not a Linux shutdown. Sleep and stop backend still explicitly stops the backend. See MANUAL_CONTROLS.md for limits and the differences from the desktop.
