import SwiftUI
import RealityKit
import ARKit
import Combine

/// World-tracked overlay. Tap a detected surface (canvas, wall, table) to pin the
/// reference image to it, then drag / pinch / twist to line it up with the canvas.
struct ARTraceView: UIViewRepresentable {
    @EnvironmentObject private var settings: OverlaySettings

    func makeCoordinator() -> ARTraceCoordinator {
        ARTraceCoordinator()
    }

    func makeUIView(context: Context) -> ARView {
        let arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        context.coordinator.attach(to: arView, settings: settings)
        return arView
    }

    func updateUIView(_ uiView: ARView, context: Context) {}

    static func dismantleUIView(_ uiView: ARView, coordinator: ARTraceCoordinator) {
        coordinator.detach()
    }
}

final class ARTraceCoordinator: NSObject {
    private weak var arView: ARView?
    private weak var settings: OverlaySettings?
    private var cancellables = Set<AnyCancellable>()

    /// World anchor at the tapped point on the surface. Its Y axis is the surface normal.
    private var anchor: AnchorEntity?
    /// Gesture target. Holds the user's drag / scale / twist adjustments.
    private var container: ModelEntity?
    /// The textured plane. Holds only the "upright" correction for the surface.
    private var quad: ModelEntity?
    private var gestures: [UIGestureRecognizer] = []
    private var texture: TextureResource?
    /// Image height divided by width.
    private var imageAspect: Float = 1

    // MARK: Lifecycle

    func attach(to arView: ARView, settings: OverlaySettings) {
        self.arView = arView
        self.settings = settings

        arView.renderOptions.insert([
            .disableMotionBlur,
            .disableDepthOfField,
            .disableHDR,
            .disableCameraGrain,
            .disableGroundingShadows,
            .disableAREnvironmentLighting
        ])
        runSession(resetTracking: true)

        let coaching = ARCoachingOverlayView()
        coaching.session = arView.session
        coaching.goal = .anyPlane
        coaching.activatesAutomatically = true
        coaching.translatesAutoresizingMaskIntoConstraints = false
        arView.addSubview(coaching)
        NSLayoutConstraint.activate([
            coaching.leadingAnchor.constraint(equalTo: arView.leadingAnchor),
            coaching.trailingAnchor.constraint(equalTo: arView.trailingAnchor),
            coaching.topAnchor.constraint(equalTo: arView.topAnchor),
            coaching.bottomAnchor.constraint(equalTo: arView.bottomAnchor)
        ])

        let tap = UITapGestureRecognizer(target: self, action: #selector(handleTap(_:)))
        arView.addGestureRecognizer(tap)

        // @Published fires on willSet, so hop to the next main-queue pass before
        // reading settings back. That way every handler sees the new value.
        settings.$processedImage
            .receive(on: DispatchQueue.main)
            .sink { [weak self] image in self?.updateTexture(image) }
            .store(in: &cancellables)
        settings.$opacity
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.applyMaterial() }
            .store(in: &cancellables)
        settings.$isLocked
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.applyLock()
                self?.refreshStatus()
            }
            .store(in: &cancellables)
        settings.$sourceImage
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refreshStatus() }
            .store(in: &cancellables)
        settings.$canvasWidthCentimeters
            .removeDuplicates()
            .dropFirst()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.rebuildQuad() }
            .store(in: &cancellables)
        settings.$handOcclusion
            .removeDuplicates()
            .dropFirst()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.runSession(resetTracking: false) }
            .store(in: &cancellables)
        settings.resetRequests
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.removePlacement() }
            .store(in: &cancellables)
        settings.quarterTurnRequests
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.rotateQuarterTurn() }
            .store(in: &cancellables)

        // makeUIView runs inside a SwiftUI update; publish state on the next pass.
        DispatchQueue.main.async { [weak self] in
            self?.settings?.hasPlacement = false
            self?.refreshStatus()
        }
    }

    func detach() {
        cancellables.removeAll()
        arView?.session.pause()
        arView = nil
    }

    private func runSession(resetTracking: Bool) {
        guard let arView else { return }
        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal, .vertical]
        configuration.environmentTexturing = .none
        configuration.isLightEstimationEnabled = false
        if settings?.handOcclusion ?? false,
           ARWorldTrackingConfiguration.supportsFrameSemantics(.personSegmentationWithDepth) {
            configuration.frameSemantics.insert(.personSegmentationWithDepth)
        }
        let options: ARSession.RunOptions = resetTracking ? [.resetTracking, .removeExistingAnchors] : []
        arView.session.run(configuration, options: options)
    }

    // MARK: Placement

    @objc private func handleTap(_ recognizer: UITapGestureRecognizer) {
        guard let arView, let settings else { return }
        guard settings.hasImage else {
            settings.statusMessage = "Pick a reference image first"
            return
        }
        guard !settings.isLocked else { return }

        let point = recognizer.location(in: arView)
        if let container, let hit = arView.entity(at: point), hit === container || hit.parent === container {
            // Tapping the overlay itself is handled by the entity gestures.
            return
        }
        guard let result = arView.raycast(from: point, allowing: .estimatedPlane, alignment: .any).first else {
            settings.statusMessage = "No surface found there. Move the phone slowly and tap again."
            return
        }
        place(at: result)
    }

    private func place(at result: ARRaycastResult) {
        guard let arView, let settings else { return }

        let newAnchor = AnchorEntity(world: result.worldTransform)
        arView.scene.addAnchor(newAnchor)

        let target: ModelEntity
        if let existing = container {
            // Keep the user's scale and twist; just move to the new surface.
            target = existing
            target.setParent(newAnchor, preservingWorldTransform: false)
            target.position = .zero
        } else {
            target = ModelEntity()
            target.name = "overlayContainer"
            let plane = ModelEntity()
            plane.name = "overlayQuad"
            plane.position = SIMD3<Float>(0, 0.002, 0)
            target.addChild(plane)
            newAnchor.addChild(target)
            quad = plane
            container = target
            rebuildQuad()
            gestures = arView
                .installGestures([.translation, .rotation, .scale], for: target)
                .compactMap { $0 as? UIGestureRecognizer }
            applyLock()
        }

        if let old = anchor {
            arView.scene.removeAnchor(old)
        }
        anchor = newAnchor
        orientQuadUpright(surfaceTransform: result.worldTransform)

        settings.hasPlacement = true
        refreshStatus()
    }

    private func removePlacement() {
        if let anchor, let arView {
            arView.scene.removeAnchor(anchor)
        }
        gestures.forEach { arView?.removeGestureRecognizer($0) }
        gestures = []
        anchor = nil
        container = nil
        quad = nil
        settings?.hasPlacement = false
        refreshStatus()
    }

    private func rotateQuarterTurn() {
        guard let container else { return }
        let quarter = simd_quatf(angle: .pi / 2, axis: SIMD3<Float>(0, 1, 0))
        container.orientation = simd_mul(container.orientation, quarter)
    }

    /// Spins the quad about the surface normal so the image reads upright:
    /// on walls the image top points to the ceiling; on tables it points away from the viewer.
    private func orientQuadUpright(surfaceTransform: simd_float4x4) {
        guard let quad, let arView else { return }

        let normal = simd_normalize(simd_make_float3(surfaceTransform.columns.1))
        let camera = arView.cameraTransform.matrix
        let cameraForward = -simd_make_float3(camera.columns.2)
        let cameraUp = simd_make_float3(camera.columns.1)

        let isVertical = abs(normal.y) < 0.6
        var up: SIMD3<Float> = isVertical ? SIMD3<Float>(0, 1, 0) : cameraForward
        up -= simd_dot(up, normal) * normal
        if simd_length(up) < 1e-3 {
            up = cameraUp - simd_dot(cameraUp, normal) * normal
        }
        up = simd_normalize(up)

        let surfaceRotation = simd_float3x3(
            simd_make_float3(surfaceTransform.columns.0),
            simd_make_float3(surfaceTransform.columns.1),
            simd_make_float3(surfaceTransform.columns.2)
        )
        let localUp = surfaceRotation.transpose * up
        // The plane mesh lies in XZ with the image top at -Z. Rotate about Y so -Z lands on localUp.
        let angle = atan2(-localUp.x, -localUp.z)
        quad.orientation = simd_quatf(angle: angle, axis: SIMD3<Float>(0, 1, 0))
    }

    // MARK: Appearance

    private func updateTexture(_ image: UIImage?) {
        guard let image, let cgImage = image.cgImage else {
            texture = nil
            applyMaterial()
            return
        }
        let newAspect = Float(cgImage.height) / Float(max(cgImage.width, 1))
        do {
            if #available(iOS 18.0, *) {
                texture = try TextureResource(image: cgImage, options: .init(semantic: .color))
            } else {
                texture = try TextureResource.generate(from: cgImage, options: .init(semantic: .color))
            }
        } catch {
            texture = nil
        }
        if abs(newAspect - imageAspect) > 0.0001 {
            imageAspect = newAspect
            rebuildQuad()
        } else {
            applyMaterial()
        }
    }

    private func rebuildQuad() {
        guard let quad, let settings else { return }
        let width = Float(max(settings.canvasWidthCentimeters, 2) / 100)
        let depth = width * imageAspect
        quad.model = ModelComponent(
            mesh: .generatePlane(width: width, depth: depth),
            materials: [makeMaterial()]
        )
        container?.collision = CollisionComponent(
            shapes: [.generateBox(width: width, height: 0.01, depth: depth)]
        )
    }

    private func makeMaterial() -> UnlitMaterial {
        var material = UnlitMaterial()
        if let texture {
            material.color = .init(tint: .white, texture: .init(texture))
        } else {
            material.color = .init(tint: .gray)
        }
        let opacity = Float(settings?.opacity ?? 0.5)
        material.blending = .transparent(opacity: PhysicallyBasedMaterial.Opacity(floatLiteral: opacity))
        return material
    }

    private func applyMaterial() {
        guard let quad, quad.model != nil else { return }
        quad.model?.materials = [makeMaterial()]
    }

    private func applyLock() {
        let locked = settings?.isLocked ?? false
        gestures.forEach { $0.isEnabled = !locked }
    }

    private func refreshStatus() {
        guard let settings else { return }
        if !settings.hasImage {
            settings.statusMessage = "Pick a reference image to get started"
        } else if !settings.hasPlacement {
            settings.statusMessage = "Aim at your canvas, then tap where the image should go"
        } else if settings.isLocked {
            settings.statusMessage = "Locked. Tap the lock to adjust."
        } else {
            settings.statusMessage = "Drag to move · pinch to resize · twist to rotate · tap elsewhere to re-place"
        }
    }
}
