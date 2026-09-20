import SwiftUI
import Combine

/// Fixed overlay for when the phone sits on a tripod or stand aimed at the canvas.
/// The image is positioned in screen space; move the phone and the overlay stays put.
struct TripodOverlayView: View {
    @EnvironmentObject private var settings: OverlaySettings

    @State private var offset: CGSize = .zero
    @State private var scale: CGFloat = 1
    @State private var rotation: Angle = .zero

    @GestureState private var dragDelta: CGSize = .zero
    @GestureState private var pinchDelta: CGFloat = 1
    @GestureState private var twistDelta: Angle = .zero

    private let minScale: CGFloat = 0.1
    private let maxScale: CGFloat = 12

    var body: some View {
        ZStack {
            CameraPreview()
                .ignoresSafeArea()

            if let image = settings.processedImage {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(24)
                    .opacity(settings.opacity)
                    .scaleEffect(clamped(scale * pinchDelta))
                    .rotationEffect(rotation + twistDelta)
                    .offset(
                        width: offset.width + dragDelta.width,
                        height: offset.height + dragDelta.height
                    )
                    .allowsHitTesting(false)
            }
        }
        .contentShape(Rectangle())
        .gesture(adjustmentGesture, including: settings.isLocked ? .none : .all)
        .onAppear(perform: refreshStatus)
        .onChange(of: settings.isLocked) { _, _ in refreshStatus() }
        .onChange(of: settings.sourceImage) { _, _ in refreshStatus() }
        .onReceive(settings.resetRequests) {
            withAnimation(.easeOut(duration: 0.2)) {
                offset = .zero
                scale = 1
                rotation = .zero
            }
        }
        .onReceive(settings.quarterTurnRequests) {
            withAnimation(.easeOut(duration: 0.2)) {
                rotation += .degrees(90)
            }
        }
    }

    private var adjustmentGesture: some Gesture {
        let drag = DragGesture(minimumDistance: 1)
            .updating($dragDelta) { value, state, _ in
                state = value.translation
            }
            .onEnded { value in
                offset.width += value.translation.width
                offset.height += value.translation.height
            }

        let pinch = MagnifyGesture()
            .updating($pinchDelta) { value, state, _ in
                state = value.magnification
            }
            .onEnded { value in
                scale = clamped(scale * value.magnification)
            }

        let twist = RotateGesture()
            .updating($twistDelta) { value, state, _ in
                state = value.rotation
            }
            .onEnded { value in
                rotation += value.rotation
            }

        return drag.simultaneously(with: pinch.simultaneously(with: twist))
    }

    private func clamped(_ value: CGFloat) -> CGFloat {
        min(max(value, minScale), maxScale)
    }

    private func refreshStatus() {
        if !settings.hasImage {
            settings.statusMessage = "Pick a reference image to get started"
        } else if settings.isLocked {
            settings.statusMessage = "Locked. Tap the lock to adjust."
        } else {
            settings.statusMessage = "Mount the phone, then drag · pinch · twist the image over your canvas"
        }
    }
}
