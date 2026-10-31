## Changes

- Manual controls no longer get stuck when the robot's measured pose sits slightly past a limit (seen on the robot: Head roll measured at 0.53 rad after a 0.5 rad target, which made every slider and center button fail with "Combined pose exceeds Head roll range"). The next movement pulls such an axis back onto the limit, and its path never goes beyond where the robot already is. Requests beyond a limit are still rejected.

## Impact

Only the manual-control target calculation changes. Other entities, polling, camera code, media dependencies and icons are unchanged.

## Notes

Update through HACS and restart Home Assistant.
