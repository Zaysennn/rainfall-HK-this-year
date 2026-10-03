# Cinematic Victoria Harbour assets

Generated with the built-in image_gen tool on 2026-10-03. No API fallback, external photographs or CLI generation were used. Originals remain in the default Codex generated-images cache.

These are illustrative weather scenes, not photographs of the selected date. Rain, wet-window motion and lightning are rendered separately by the viewer. The complete 3:1 skyline stays inside the frame.

The wet-glass atlas has 4 columns and 4 rows. Divide its 1254-pixel width and height by 4 when choosing each source rectangle; fractional Canvas source coordinates preserve the full atlas. Its alpha channel is preserved unchanged.

## harbour-sun-cinematic.png

- Dimensions: 2172 x 724; RGB.
- SHA-256: ad0dbad4e8dd281297390241a9214487ee3b4ae6381a02c43a278e9eb2801b3e
- Composition reference: ../../.backups/harbour-cinematic-window-20261003/qa/reference-sun.png
- Generated source: C:\Users\12854\.codex\generated_images\01a10158-0b63-7972-9b5c-d60edc97e4e7\exec-b2b4bbe1-036c-4ab2-bee1-f191ae87dfdf.png

### Exact generation prompt

```text
Use case: lighting-weather
Asset type: a photographic Victoria Harbour panorama for the upper background of a weather-data website.
Input images: Image 1 is the exact composition and geometry reference to preserve.
Primary request: create a new cinematic golden clear-weather variant of this full Hong Kong Island coastline. The waterfront, complete skyline, hill ridgeline, iconic building identities, horizon and camera viewpoint must remain at the identical positions and sizes. Preserve the full 3:1 wide panorama with all buildings inside the frame.
Style/medium: convincing real-location cinematic photography, elegant natural fine film grain, realistic glass and concrete texture, gentle atmospheric depth.
Lighting/mood: luminous clear blue sky with warm golden sunlight across the entire coast, radiant rays softly entering from the upper right, a serene uplifting sacred golden-hour feeling, warm water reflections, tasteful highlight rolloff.
Color palette: golden cream highlights, naturally blue clear sky and water, no orange monochrome.
Composition/framing: exact existing composition, one continuous landscape photograph, no panels, no crop, wide 3:1 image.
Constraints: change lighting and fine grain only; keep skyline geometry and coastline unchanged. This is the clean background for separately animated rain and wet-glass layers. No foreground glass, droplets, rain streaks, lightning, foreground objects, lettering, logo, watermarks, illustration or UI.
Output: a single opaque PNG panorama, as wide 3:1 as the reference.
```

## harbour-mist-cinematic.png

- Dimensions: 2172 x 724; RGB.
- SHA-256: bd30105c6f5d0e54c2437e34431320aa15ac449e406542b47512e7fa75fa83c1
- Composition reference: harbour-sun-cinematic.png
- Generated source: C:\Users\12854\.codex\generated_images\01a10158-0b63-7972-9b5c-d60edc97e4e7\exec-b9722881-9948-4f94-9878-95d35d02e077.png

### Exact generation prompt

```text
Use case: lighting-weather
Asset type: a photographic Victoria Harbour panorama for the upper background of a weather-data website.
Input images: Image 1 is the exact new sunny panorama to transform. It locks the whole coastline, building geometry, horizon, viewpoint and full 3:1 composition.
Primary request: change only the time-of-day, lighting and weather into a cinematic moderate-rain overcast afternoon. Preserve every building's shape and exact position, the hills and coastline, full sky and water proportions and complete panorama.
Style/medium: photorealistic real-location cinematic photography with fine organic film grain. The background looks softly distant through atmospheric moisture, still clearly recognizable. Keep sufficient building definition; not a blank uniform fog.
Lighting/mood: layered slate-grey rain clouds rolling across the sky, subdued diffuse daylight, soft grey mist around hills and middle-distance towers, moist reflected light on the harbour water. Gently shallow depth of field so city background edges feel soft, as a scene to later view through rain on a window.
Color palette: cool silver-grey, muted teal-blue water, gentle neutral daylight, dimensional clouds.
Composition/framing: identical existing single continuous 3:1 skyline photograph, no crop, no panels.
Constraints: preserve architecture, landmark identities, coastline, camera position and image geometry exactly. Only lighting, clouds and fog may change. No glass, water droplets on the lens/window, rain streaks in foreground or background, lightning, foreground objects, text, logo or watermark. Rain and glass will be animated separately in the website.
Output: a single opaque PNG panorama with the same wide 3:1 image geometry.
```

## harbour-night-cinematic.png

- Dimensions: 2172 x 724; RGB.
- SHA-256: 44e775be442a9b8843dc3bfaa76d50d4aed0e963590971921bd2c22b2fd6bb1a
- Composition reference: harbour-sun-cinematic.png
- Generated source: C:\Users\12854\.codex\generated_images\01a10158-0b63-7972-9b5c-d60edc97e4e7\exec-022f6095-7b41-4f6b-a5e3-f97f85a0fc16.png

### Exact generation prompt

```text
Use case: lighting-weather
Asset type: a cinematic photographic Victoria Harbour night panorama for a weather-data website background.
Input images: Image 1 is the exact new sunny panorama to transform. It locks the complete coastline, building geometry, hill ridgeline, horizon, viewpoint and full 3:1 composition.
Primary request: change only lighting, time and weather into a deep-blue Hong Kong harbour rain-night. Turn on believable warm interior office windows and harbourfront city lights. Preserve every landmark's position and silhouette, coastline and full panorama exactly.
Style/medium: photorealistic cinematic location photography with fine organic film grain, filmic highlight rolloff and soft moisture haze. Slight shallow-depth-of-field background softness with natural small warm city-light bokeh and glow; retain readable iconic skyline silhouettes. This is a background to be viewed through animated wet glass later.
Lighting/mood: dramatic layered navy storm clouds, deep midnight-blue atmosphere with luminous blue detail rather than pure black, damp cool shadows, warm amber city lights reflected softly in the water. Subtle dim violet tint in the upper cloud banks, but no visible lightning baked into the photograph.
Color palette: rich cinematic navy, slate-blue water, cool steel-blue city edges, restrained warm amber and cream lights, delicate violet cloud undertone.
Composition/framing: identical existing single continuous 3:1 skyline photograph, no crop, no panels. All building tops and full waterfront stay in frame.
Constraints: preserve architecture, landmark identities, hills, skyline camera geometry, horizon and water proportions exactly. Change only lighting, fog, clouds and time. No foreground glass, lens droplets, water drops, rain streaks, lightning bolts, human silhouettes, text, logos or watermarks. Glass and rain will be separately animated, and purple lightning will be dynamic.
Output: a single opaque PNG panorama matching the same wide 3:1 geometry.
```

## glass-droplets.png

- Dimensions: 1254 x 1254; RGBA.
- SHA-256: 1a3ba690e31ee4bad47a9b0e282c7237a1d93812ccdcae16f902ee54477abe89
- Composition reference: none (new transparent image)
- Generated source: C:\Users\12854\.codex\generated_images\01a10158-0b63-7972-9b5c-d60edc97e4e7\exec-173cb087-d53b-4157-8de7-54867e7565cb.png

- Verified alpha pixels: {"opaque": 110, "partial": 525282, "transparent": 1047124}.

### Exact generation prompt

```text
Use case: photorealistic-natural
Asset type: transparent PNG sprite atlas of photographic water droplets on a vertical window pane, for animation over a distant cinematic city panorama.
Primary request: sixteen separate natural wet-glass droplets arranged as exactly 4 columns by 4 rows in evenly sized invisible square cells, one isolated droplet centered in each cell. This is an image asset, not a picture of a sheet or window scene. Output one square transparent PNG with genuine alpha.
Subject: sixteen varied irregular clear water drops, including rounded asymmetric drops, wider coalesced beads, gentle oval hanging drops, small elongated drips and a few very short tapered tails. Each object fits within the middle 65 percent of its cell, leaving transparent margins and no overlap between cells. Same approximate photographic scale across the atlas.
Style/medium: macro photographic optical realism: mostly transparent water interiors, subtly refracting lens contours, delicate thin cool grey edge shadows, one restrained white catchlight and tiny lower reflected highlight; shapes have real surface tension and asymmetry. Tiny smooth optical distortion hints inside otherwise transparent centers.
Lighting: neutral soft side light suitable over both a grey overcast city and blue city night.
Constraints: the space between objects and outside all droplets is actually transparent, and the drop centers are semitransparent rather than white filled discs. No hard white rings, no opaque blobs, no soap bubbles, no white background, no black background, no checkerboard baked in, no pane rectangle, no city scene, no photograph border, no ground or cast shadow, no cell outlines, no text, no labels, no watermark. No droplets beyond the sixteen. Every row and column is regular enough for code to crop the sixteen equal cells without cutting a droplet.
Output: square RGBA PNG with a genuinely transparent background, exactly a 4 by 4 atlas of 16 distinct separated realistic clear wet-glass droplets.
```
