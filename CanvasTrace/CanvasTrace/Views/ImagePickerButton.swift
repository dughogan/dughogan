import SwiftUI
import PhotosUI

/// Photos picker that loads, normalizes, and hands the image to the shared settings.
struct ImagePickerButton: View {
    enum Style {
        case prominent
        case toolbar
    }

    @EnvironmentObject private var settings: OverlaySettings
    @State private var selection: PhotosPickerItem?
    @State private var isLoading = false

    var style: Style = .toolbar

    var body: some View {
        PhotosPicker(selection: $selection, matching: .images, photoLibrary: .shared()) {
            switch style {
            case .prominent:
                Label(isLoading ? "Loading…" : "Choose Image", systemImage: "photo.on.rectangle.angled")
                    .font(.headline)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(Color.accentColor, in: Capsule())
                    .foregroundStyle(.black)
            case .toolbar:
                ToolbarTile(title: "Image", systemImage: "photo.on.rectangle.angled", isActive: false)
            }
        }
        .disabled(isLoading)
        .onChange(of: selection) { _, item in
            guard let item else { return }
            load(item)
        }
    }

    private func load(_ item: PhotosPickerItem) {
        isLoading = true
        Task { @MainActor in
            defer { isLoading = false }
            guard let data = try? await item.loadTransferable(type: Data.self),
                  let picked = UIImage(data: data) else {
                settings.statusMessage = "Couldn't load that image. Try another one."
                return
            }
            let normalized = await Task.detached(priority: .userInitiated) {
                ImageProcessor.normalized(picked)
            }.value
            settings.sourceImage = normalized
            selection = nil
        }
    }
}

/// Compact icon-over-label tile used across the bottom toolbar.
struct ToolbarTile: View {
    var title: String
    var systemImage: String
    var isActive: Bool

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: systemImage)
                .font(.system(size: 20, weight: .medium))
                .frame(height: 24)
            Text(title)
                .font(.caption2)
                .lineLimit(1)
        }
        .frame(width: 64, height: 56)
        .foregroundStyle(isActive ? Color.accentColor : Color.white)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(isActive ? Color.accentColor.opacity(0.18) : Color.white.opacity(0.06))
        )
    }
}
