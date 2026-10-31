# Manual controls (0.2.8)

These controls belong to the HA integration. They do not change the voice app,
daemon, host services or camera path.

## Controls

Head X/Y/Z use metres (m). Head yaw/pitch/roll, body yaw and antennas use radians
(rad), matching desktop 0.9.37. Movement duration is an HA preference, 0.5–5 s,
default 1 s. Head follows body defaults to off. Both preferences reset on reload.

Head follows body rotates the whole head transform around the body's yaw axis,
including X/Y translation. Head roll and pitch are preserved. It applies only to
Body yaw and Center body. Changing the switch never moves the robot.

With linking off, Head yaw is a world-frame heading, limited to ±1.2 rad.
With linking on it remains a world heading, displayed over ±pi; the relative
head/body yaw is still limited to ±65 degrees. This wider world-heading display
is necessary to turn head and body together past ±1.2 rad. It is not an expanded
neck range. Turning linking off does not recenter the robot; an existing heading
outside ±1.2 rad may be displayed until a valid new target is chosen.

Center head resets X/Y/Z, roll and pitch; yaw becomes zero with linking off or
the body's yaw with linking on. Center body resets the body only, with the head
following when linking is on. Center all resets all axes, including antennas, to
the desktop controller's zero target (not a sleep or wake pose).

## Limits

Desktop send limits: XYZ ±0.05 m, pitch ±0.8 rad, roll ±0.5 rad,
independent head yaw ±1.2 rad, body and antennas ±160 degrees in radians.
The daemon's analytical solver uses a ±65-degree relative head/body yaw limit.
We reject invalid combined targets instead of relying on the solver to change
the requested body yaw. Individual limits do not guarantee every compound pose
is mechanically reachable. Limits apply to sampled trajectory points too.
A measured start pose slightly past a limit (servo and kinematics tolerance,
e.g. roll 0.53 rad after a 0.5 rad target) does not block control: the next
target pulls that axis back onto the limit, and sampled points stay between the
start pose and the target. Requests beyond a limit are still rejected.

## Availability and state

The integration uses its normal 30-second coordinator poll plus post-action
refresh. It adds GETs for /api/apps/current-app-status, /api/state/full and
/api/move/running to that poll. Availability uses this cached state; no app status, app ownership or motor
mode query precedes an action. A movement reads /api/state/full once for a fresh
start pose and sends nothing if that read fails. While the backend runs, one or
two failed pose reads in the poll keep the last pose instead of greying out.

Controls are unavailable when the backend is not running, the robot is not awake,
an app/session is active, a move is running, relevant state is unknown, a hardware
error is reported, an integration lifecycle command is in progress or a recorded
move started from HA is playing. The integration's own movement does not make
the controls unavailable.
The existing app-slot data contributes to the cached active-app/session state;
manual controls do not acquire the app lock or issue a separate ownership query.

The desktop also knows its own local installation and UI transition states.
HA cannot see every desktop-local transition, so this is aligned behavior,
not a copy of the desktop's internal state machine. Cached state can lag changes
made by other clients by up to a poll interval. This is not an exclusive control
lease: do not operate two controllers at once.

## Motion transport

Use the official /api/move/set_target REST endpoint (desktop's HTTP fallback).
HA sends a finite smoothstep trajectory, no faster than 20 requests per second,
only during a user action. A slow network stretches the duration instead of
bursting overdue frames. No idle command writer or permanent control WebSocket
is created. The requested duration is nominal, not a real-time guarantee.

A daemon 'ignored' response (a recorded move is playing) is an action failure,
not success. New cached busy
state interrupts remaining frames. One writer runs at a time: a new
action during a movement continues from the frame being sent toward the combined
target (the earlier change plus the new one) instead of failing or queueing
stale targets. Head follows body linking along the path applies to a movement
that starts fresh; a combined path is still validated sample by sample. Unloading the
integration cancels any remaining HA writes. Accepted targets are not proof of
physical arrival; the next refresh displays measured feedback.

This is intentionally not the desktop's frame-rate-dependent smoothing algorithm.
HA number service calls do not expose the same drag lifecycle.

## Power Off

The button checks cached availability, reads Startup app configuration, requests
goto_sleep, waits the desktop's 6 s (4 s without a move UUID), disables motors,
then retains the backend when Startup app is set. Otherwise it stops the backend
with goto_sleep=false and waits for that job. It does not power down Linux.

Unlike desktop best-effort shutdown, a request/configuration failure is surfaced
instead of silently continuing. A sleep UUID acknowledges scheduling, not
physical arrival. No force-stop of an active app is performed by this button.
Go to sleep (formerly named Sleep and stop backend) keeps its own app-stop sequence.

## Validation

Cloud tests cover requests, state gates, full-pose coupling, limits, failures,
concurrency, unload cancellation and the existing lifecycle/camera/media tests.
Physical direction signs, compound pose reachability, idle-reset interaction and
Startup-app antenna wake still require robot testing after installation.
