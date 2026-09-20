import SwiftUI
import Combine

/// Image treatments that make a reference easier to trace or block in.
enum TraceFilter: String, CaseIterable, Identifiable {
    case original
    case grayscale
    case highContrast
    case posterize
    case sketch

    var id: String { rawValue }

    var label: String {
        switch self {
        case .original: return "Original"
        case .grayscale: return "Grayscale"
        case .highContrast: return "Contrast"
        case .posterize: return "Values"
        case .sketch: return "Sketch"
        }
    }

    var systemImage: String {
        switch self {
        case .original: return "photo"
        case .grayscale: return "circle.lefthalf.filled"
        case .highContrast: return "circle.righthalf.filled"
        case .posterize: return "square.stack.3d.up"
        case .sketch: return "pencil.and.outline"
        }
    }
}

enum ViewMode: String, CaseIterable, Identifiable {
    /// World-tracked overlay pinned to the physical canvas.
    case ar
    /// Fixed 2D overlay on the live camera, for a phone mounted on a tripod.
    case tripod

    var id: String { rawValue }

    var label: String {
        switch self {
        case .ar: return "AR"
        case .tripod: return "Tripod"
        }
    }

    var systemImage: String {
        switch self {
        case .ar: return "arkit"
        case .tripod: return "camera.viewfinder"
        }
    }
}

enum LengthUnit: String, CaseIterable, Identifiable {
    case centimeters
    case inches

    var id: String { rawValue }

    var label: String {
        switch self {
        case .centimeters: return "cm"
        case .inches: return "in"
        }
    }

    var centimetersPerUnit: Double {
        switch self {
        case .centimeters: return 1
        case .inches: return 2.54
        }
    }
}

/// Everything ImageProcessor needs to turn the source image into the overlay image.
struct ProcessingRequest: Equatable {
    var filter: TraceFilter
    /// 0 means no grid.
    var gridDivisions: Int
    var flipped: Bool
}

/// Shared state for both view modes. All mutation happens on the main thread.
final class OverlaySettings: ObservableObject {
    @Published var sourceImage: UIImage? { didSet { scheduleProcessing() } }
    @Published var opacity: Double = 0.5
    @Published var filter: TraceFilter = .original { didSet { scheduleProcessing() } }
    @Published var showGrid = false { didSet { scheduleProcessing() } }
    @Published var gridDivisions = 4 { didSet { scheduleProcessing() } }
    @Published var isFlipped = false { didSet { scheduleProcessing() } }
    @Published var isLocked = false
    @Published var mode: ViewMode = .ar
    @Published var lengthUnit: LengthUnit = .inches
    /// Real-world width of the overlay when it is first placed in AR.
    @Published var canvasWidthCentimeters: Double = 40.64
    @Published var handOcclusion = true
    @Published var hasPlacement = false
    @Published var statusMessage: String?
    @Published private(set) var processedImage: UIImage?
    @Published private(set) var isProcessing = false

    /// Fires when the user asks to clear the current placement / transform.
    let resetRequests = PassthroughSubject<Void, Never>()
    /// Fires when the user asks for a quarter turn of the overlay.
    let quarterTurnRequests = PassthroughSubject<Void, Never>()

    private var processingToken = UUID()

    var hasImage: Bool { sourceImage != nil }

    var canvasWidthInSelectedUnit: Double {
        get { canvasWidthCentimeters / lengthUnit.centimetersPerUnit }
        set { canvasWidthCentimeters = max(newValue, 1) * lengthUnit.centimetersPerUnit }
    }

    func resetPlacement() {
        resetRequests.send()
    }

    func rotateQuarterTurn() {
        quarterTurnRequests.send()
    }

    private func scheduleProcessing() {
        guard let source = sourceImage else {
            processedImage = nil
            isProcessing = false
            return
        }
        let request = ProcessingRequest(
            filter: filter,
            gridDivisions: showGrid ? gridDivisions : 0,
            flipped: isFlipped
        )
        let token = UUID()
        processingToken = token
        isProcessing = true
        DispatchQueue.global(qos: .userInitiated).async {
            let output = ImageProcessor.process(source, request: request)
            DispatchQueue.main.async { [weak self] in
                guard let self, self.processingToken == token else { return }
                self.processedImage = output
                self.isProcessing = false
            }
        }
    }
}
