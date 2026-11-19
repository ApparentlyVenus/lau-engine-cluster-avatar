# 3D patient

`avatar.js` shows the patient in the Session view with
[TalkingHead](https://github.com/met4citizen/TalkingHead) (MIT, vendored in
`../vendor/talkinghead`) on [three.js](https://threejs.org) r186 (MIT, vendored
in `../vendor/three`). No build step: `index.html` maps the imports.

## How it is driven

- **Emotion:** every `state` event sets the face. The emotion picks a base
  expression, the undertone is blended in, intensity scales it, and the active
  defense adds a mask on top (`FACES` and `MASKS` in `avatar.js`). Each
  emotion also sets posture (head down in grief), gaze (low eye contact in
  shock and grief) and how much the head moves (almost frozen in shock). When
  an emotion or defense first appears, a short reaction plays (for example a
  rolled eye for sarcasm); if she is talking at that moment, it waits until
  she stops so it does not fight the lip sync.
- **Idle motion:** kept small on purpose. TalkingHead's stock moods switch
  poses, sweep the head and twitch the mouth and brows at random; here only
  breathing, blinking, eye movement and a small head drift remain, and there
  are no hand gestures while talking. Measured in a headless browser over
  20 s at rest: head movement down from about 7 to 9 degrees (standard
  deviation of yaw) to about 1, random face twitching down about 6 times.
- **Lip sync:** the server sends each word's position in the audio
  (`pipeline/lipsync.py`). The page plays the voice as before; a silent copy of
  the audio goes to TalkingHead as the clock, and each word is handed over once
  its audio has arrived. English only for now (TalkingHead has no Arabic
  lip-sync module).

## The model

`patient.glb` is TalkingHead's MPFB example avatar, made with Blender and the
[MPFB](https://static.makehumancommunity.org/mpfb.html) extension, licensed
[CC0](https://creativecommons.org/public-domain/cc0/). It was compressed from
36.8 MB to 3 MB with gltf-transform (textures resized to 1024 px and converted
to WebP, meshes compressed with meshopt):

    gltf-transform resize mpfb.glb a.glb --width 1024 --height 1024
    gltf-transform webp a.glb b.glb
    gltf-transform meshopt b.glb patient.glb

It is a placeholder, not Layla: a young woman in a T-shirt. Each patient can
point to their own model in their character file:

    "avatar": { "url": "/static/avatar/layla.glb", "body": "F" }

A model needs a Mixamo-compatible rig plus ARKit and Oculus viseme
blendshapes. MPFB in Blender makes one of any age and build for free; see
TalkingHead's `blender/MPFB/MPFB.md`. Keep files under about 4 MB (compress as
above): hosted on Vercel, larger responses are refused.
