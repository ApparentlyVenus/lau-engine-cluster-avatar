# 3D patient

`avatar.js` shows the patient in the Session view with
[TalkingHead](https://github.com/met4citizen/TalkingHead) (MIT, vendored in
`../vendor/talkinghead`) on [three.js](https://threejs.org) r186 (MIT, vendored
in `../vendor/three`). No build step: `index.html` maps the imports.

## How it is driven

- **Emotion:** every `state` event from the state engine sets the face. The
  emotion picks a base expression, the undertone is blended in, intensity
  scales it, and the active defense adds a mask on top (`FACES` and `MASKS` in
  `avatar.js`). Gaze also follows the emotion (low eye contact in shock and
  grief).
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
