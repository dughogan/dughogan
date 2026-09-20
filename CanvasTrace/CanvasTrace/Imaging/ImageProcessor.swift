import UIKit
import CoreImage
import CoreImage.CIFilterBuiltins

/// Core Image pipeline that produces the overlay texture from the picked photo.
enum ImageProcessor {
    /// Longest edge of the working image. Keeps texture uploads and filtering fast.
    static let maxDimension: CGFloat = 2048

    private static let context = CIContext(options: [.cacheIntermediates: false])

    /// Redraws the image upright at scale 1 and capped to `maxDimension`.
    /// UIImage orientation metadata is baked in so later CGImage work is straightforward.
    static func normalized(_ image: UIImage) -> UIImage {
        let size = image.size
        let longest = max(size.width, size.height, 1)
        let scale = min(1, maxDimension / longest)
        let target = CGSize(
            width: max(1, (size.width * scale).rounded()),
            height: max(1, (size.height * scale).rounded())
        )
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        format.opaque = false
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
    }

    static func process(_ image: UIImage, request: ProcessingRequest) -> UIImage? {
        guard let sourceCG = image.cgImage else { return nil }
        var working = CIImage(cgImage: sourceCG)
        let extent = working.extent

        switch request.filter {
        case .original:
            break

        case .grayscale:
            let mono = CIFilter.photoEffectMono()
            mono.inputImage = working
            working = mono.outputImage ?? working

        case .highContrast:
            let controls = CIFilter.colorControls()
            controls.inputImage = working
            controls.saturation = 0
            controls.contrast = 1.6
            controls.brightness = 0.02
            working = controls.outputImage ?? working

        case .posterize:
            let mono = CIFilter.photoEffectMono()
            mono.inputImage = working
            let posterize = CIFilter.colorPosterize()
            posterize.inputImage = mono.outputImage
            posterize.levels = 5
            working = posterize.outputImage ?? working

        case .sketch:
            let lines = CIFilter.lineOverlay()
            lines.inputImage = working
            lines.nrNoiseLevel = 0.07
            lines.nrSharpness = 0.71
            lines.edgeIntensity = 1.0
            lines.threshold = 0.1
            lines.contrast = 50
            let paper = CIImage(color: CIColor(red: 1, green: 1, blue: 1)).cropped(to: extent)
            let composite = CIFilter.sourceOverCompositing()
            composite.inputImage = lines.outputImage
            composite.backgroundImage = paper
            working = composite.outputImage ?? working
        }

        working = working.cropped(to: extent)
        if request.flipped {
            working = working.oriented(.upMirrored)
        }

        guard let outputCG = context.createCGImage(working, from: working.extent) else { return nil }
        var output = UIImage(cgImage: outputCG)
        if request.gridDivisions > 1 {
            output = drawGrid(on: output, divisions: request.gridDivisions)
        }
        return output
    }

    private static func drawGrid(on image: UIImage, divisions: Int) -> UIImage {
        let size = image.size
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        format.opaque = false
        return UIGraphicsImageRenderer(size: size, format: format).image { rendererContext in
            image.draw(in: CGRect(origin: .zero, size: size))
            let cg = rendererContext.cgContext
            let lineWidth = max(2, min(size.width, size.height) / 400)
            cg.setLineWidth(lineWidth)
            cg.setStrokeColor(UIColor.systemRed.withAlphaComponent(0.85).cgColor)
            for index in 1..<divisions {
                let fraction = CGFloat(index) / CGFloat(divisions)
                let x = size.width * fraction
                let y = size.height * fraction
                cg.move(to: CGPoint(x: x, y: 0))
                cg.addLine(to: CGPoint(x: x, y: size.height))
                cg.move(to: CGPoint(x: 0, y: y))
                cg.addLine(to: CGPoint(x: size.width, y: y))
            }
            cg.strokePath()
            cg.stroke(CGRect(origin: .zero, size: size).insetBy(dx: lineWidth / 2, dy: lineWidth / 2))
        }
    }
}
