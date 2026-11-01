# Manual controls (0.2.9)

These controls belong to the HA integration. They do not change the voice app,
daemon, host services or camera path. They follow the desktop controller
(desktop 0.9.37) unless noted.

## Controls

Head X/Y/Z use metres (m). Head yaw/pitch/roll, body yaw and antennas use radians
(rad), shown with three decimals like the desktop. Movement duration is an HA
preference, 0.5–5 s, default 1 s. Head follows body defaults to off. Both
preferences reset on reload.

Signs follow the desktop display: positive Head X is forward, positive Head pitch
is up and positive Head yaw is right. The daemon API uses the opposite sign for
these three axes; the integration converts. Head Y/Z/roll, body yaw and antennas
use the API sign, as on the desktop.

Head follows body rotates the whole head transform around the body's yaw axis,
including X/Y translation. Head roll and pitch are preserved. It applies only to
Body yaw and Center body. Changing the switch never moves the robot.

With linking off, Head yaw is a world-frame heading, limited to ±1.2 rad.
With linking on it remains a world heading, displayed over ±pi.

Center head resets X/Y/Z, roll and pitch; yaw becomes zero with linking off or
the body's yaw with linking on. Center body resets the body only, with the head
following when linking is on. Center all resets all axes, including antennas, to
the desktop controller's zero target (not a sleep or wake pose).

## Limits

Desktop ranges: XYZ ±0.05 m, pitch ±0.8 rad, roll ±0.5 rad, head yaw ±1.2 rad,
body and antennas ±160 degrees in radians. Like the desktop, values outside a
range are clamped, not rejected. The head/body relative yaw (65 degrees) is left
to the daemon's automatic body yaw, as on the desktop: turning the head far may
turn the body a little, and turning the body far with linking off may stop short.

A measured start pose slightly past a limit (servo and kinematics tolerance,
e.g. roll 0.53 rad after a 0.5 rad target) does not block control: the next
target pulls that axis back onto the limit, and sampled points stay between the
start pose and the target.

## Start pose

Like the desktop, a movement continues from the last target HA sent. The pose is
read once from /api/state/full before a movement; only when it differs from that
target by more than the desktop's major-change threshold (0.1, summed over all
axes) is the robot considered moved elsewhere, and the measured pose is used.
If that read fails, nothing is sent.

## Availability and state

The integration uses its normal 30-second coordinator poll plus post-action
refresh. Controls are unavailable when the backend is not running, the robot is
not awake, an app/session is active, a move is running, relevant state is
unknown, a hardware error is reported, an integration lifecycle command is in
progress or a recorded move started from HA is playing. The integration's own
movement does not make the controls unavailable. While the backend runs, one or
two failed pose reads in the poll keep the last pose instead of greying out.

## Motion transport

Use the official /api/move/set_target REST endpoint (desktop's HTTP fallback).
HA sends a finite smoothstep trajectory, no faster than 20 requests per second,
only during a user action. A slow network stretches the duration instead of
bursting overdue frames. No idle command writer or permanent control WebSocket
is created. HA number sliders send on release, so this intentionally differs
from the desktop's per-frame smoothing while dragging.

A daemon 'ignored' response (a recorded move is playing) is an action failure,
not success. New cached busy state interrupts remaining frames. One writer runs
at a time: a new action during a movement continues from the frame being sent
toward the combined target instead of failing or queueing stale targets.
Unloading the integration cancels any remaining HA writes. Accepted targets are
not proof of physical arrival; the next refresh displays measured feedback.

## Power Off

The button checks cached availability, reads Startup app configuration, requests
goto_sleep, waits the desktop's 6 s (4 s without a move UUID), disables motors,
then retains the backend when Startup app is set. Otherwise it stops the backend
with goto_sleep=false and waits for that job. It does not power down Linux.
Unlike desktop best-effort shutdown, a request/configuration failure is surfaced
instead of silently continuing. Go to sleep keeps its own app-stop sequence.

## Validation

Cloud tests cover requests, state gates, signs, clamping, start pose, full-pose
coupling, failures, concurrency, unload cancellation and the existing
lifecycle/camera/media tests. Physical direction signs still require a check on
the robot after installation.
