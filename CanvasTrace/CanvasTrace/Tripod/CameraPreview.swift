import SwiftUI
import AVFoundation

/// Plain camera passthrough used by Tripod mode. No tracking, no ARKit.
struct CameraPreview: UIViewRepresentable {
    func makeCoordinator() -> CameraController {
        CameraController()
    }

    func makeUIView(context: Context) -> CameraPreviewView {
        let view = CameraPreviewView()
        view.previewLayer.videoGravity = .resizeAspectFill
        view.previewLayer.session = context.coordinator.session
        context.coordinator.start()
        return view
    }

    func updateUIView(_ uiView: CameraPreviewView, context: Context) {}

    static func dismantleUIView(_ uiView: CameraPreviewView, coordinator: CameraController) {
        coordinator.stop()
    }
}

final class CameraPreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

    var previewLayer: AVCaptureVideoPreviewLayer {
        layer as! AVCaptureVideoPreviewLayer
    }
}

final class CameraController {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "com.dughogan.CanvasTrace.camera")
    private var isConfigured = false
    private var interruptionObserver: NSObjectProtocol?

    init() {
        // If ARKit still holds the camera when we start, the session is interrupted
        // and resumes here once the camera is released.
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: .AVCaptureSessionInterruptionEnded,
            object: session,
            queue: nil
        ) { [weak self] _ in
            self?.configureAndRun()
        }
    }

    deinit {
        if let interruptionObserver {
            NotificationCenter.default.removeObserver(interruptionObserver)
        }
    }

    func start() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureAndRun()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                if granted { self?.configureAndRun() }
            }
        default:
            break
        }
    }

    func stop() {
        queue.async { [session] in
            if session.isRunning { session.stopRunning() }
        }
    }

    private func configureAndRun() {
        // Small delay so a just-paused ARSession has released the camera.
        queue.asyncAfter(deadline: .now() + 0.3) { [self] in
            if !isConfigured {
                session.beginConfiguration()
                session.sessionPreset = .high
                if let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
                   let input = try? AVCaptureDeviceInput(device: device),
                   session.canAddInput(input) {
                    session.addInput(input)
                }
                session.commitConfiguration()
                isConfigured = true
            }
            if !session.isRunning { session.startRunning() }
        }
    }
}
