# CanvasTrace

An iPhone augmented-reality app for painters. Pick a reference image, point the phone at your canvas, tap, and the image is pinned to the canvas in 3D so you can transfer proportions, outlines and value shapes without a projector or grid transfer.

Built with SwiftUI, ARKit and RealityKit. No third-party dependencies.

## Features

- **AR mode**: tap a detected surface (a stretched canvas on an easel, a board on a table, a wall) and the image is world-anchored there. Walk around, lean in, step back; it stays put.
- **Real-world sizing**: enter your canvas width in inches or centimeters and the overlay is placed at that physical size. Pinch to fine-tune.
- **Drag, pinch, twist** to line up the corners, then **lock** so a stray touch cannot move it.
- **Tripod mode**: a fixed screen-space overlay on the live camera for when the phone sits on a stand. Rock steady, no tracking drift.
- **Opacity slider** from faint ghost to full image.
- **Tracing filters**: Original, Grayscale, Contrast, Values (posterized value blocks) and Sketch (edge lines on white).
- **Grid overlay** (2×2 to 12×12) for classic grid transfer, **horizontal flip**, and **rotate 90°**.
- **Hand occlusion**: your hand and brush render in front of the overlay so you can see your strokes (A12 chip or newer).

## Requirements

- Xcode 16 or newer
- iPhone running iOS 17 or newer with ARKit support (iPhone 8 / A11 or later; hand occlusion needs A12 or later)
- A physical device. ARKit does not run in the simulator.

## Build and run

1. Open `CanvasTrace/CanvasTrace.xcodeproj` in Xcode.
2. Select the `CanvasTrace` target, then under **Signing & Capabilities** pick your team. Change the bundle identifier if `com.dughogan.CanvasTrace` collides with an existing app.
3. Plug in your iPhone, select it as the run destination, and press Run.
4. Allow camera access when prompted.

## Using it

1. Tap **Choose Image** and pick the reference photo from your library.
2. Open **Settings** (gear) and enter your canvas width so the overlay comes in at true size.
3. In **AR** mode, move the phone slowly until the coaching overlay disappears, aim at the canvas, and tap where the image should sit.
4. Drag to move, pinch to resize, twist to rotate. Tap somewhere else to re-place it on a different surface.
5. Tap the **lock** once it lines up. Adjust opacity as you work.
6. Switch to **Sketch** or **Values** to see just the edges or the big value shapes. Turn on **Grid** to transfer by eye.

Tip: good lighting and a textured background around the canvas help ARKit find the surface. A blank white wall with nothing else in view is the hardest case; hang the canvas somewhere with a bit of visual detail nearby.

## Project layout

```
CanvasTrace/
  CanvasTraceApp.swift          App entry point
  Models/OverlaySettings.swift  Shared state: image, opacity, filter, mode, canvas size
  Imaging/ImageProcessor.swift  Core Image pipeline (filters, flip, grid)
  AR/ARTraceView.swift          ARKit + RealityKit overlay, placement and gestures
  Tripod/CameraPreview.swift    AVFoundation passthrough for tripod mode
  Tripod/TripodOverlayView.swift Screen-space overlay with drag/pinch/rotate
  Views/                        SwiftUI chrome: controls, picker, settings sheet
```

## How the AR placement works

A tap raycasts against detected planes. A world anchor is created at the hit with its Y axis along the surface normal. The textured quad is a child of a gesture container: the quad carries only an "upright" correction (image top toward the ceiling on walls, away from the viewer on tables), and the container carries the user's drag, scale and rotation. Re-placing the image moves the container to a new anchor and keeps the user's adjustments.
