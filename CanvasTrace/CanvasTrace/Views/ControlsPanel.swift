import SwiftUI

/// Bottom panel: opacity slider plus the tools that change the overlay.
struct ControlsPanel: View {
    @EnvironmentObject private var settings: OverlaySettings
    @Binding var showSettings: Bool

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: "circle.dotted")
                    .foregroundStyle(.secondary)
                Slider(value: $settings.opacity, in: 0.05...1)
                    .tint(.accentColor)
                Text("\(Int((settings.opacity * 100).rounded()))%")
                    .font(.caption.monospacedDigit())
                    .frame(width: 40, alignment: .trailing)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 6)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ImagePickerButton(style: .toolbar)

                    Menu {
                        Picker("Filter", selection: $settings.filter) {
                            ForEach(TraceFilter.allCases) { filter in
                                Label(filter.label, systemImage: filter.systemImage).tag(filter)
                            }
                        }
                    } label: {
                        ToolbarTile(
                            title: settings.filter.label,
                            systemImage: settings.filter.systemImage,
                            isActive: settings.filter != .original
                        )
                    }
                    .disabled(!settings.hasImage)

                    Button {
                        settings.showGrid.toggle()
                    } label: {
                        ToolbarTile(title: "Grid", systemImage: "grid", isActive: settings.showGrid)
                    }
                    .disabled(!settings.hasImage)

                    Button {
                        settings.isFlipped.toggle()
                    } label: {
                        ToolbarTile(
                            title: "Flip",
                            systemImage: "arrow.left.and.right.righttriangle.left.righttriangle.right",
                            isActive: settings.isFlipped
                        )
                    }
                    .disabled(!settings.hasImage)

                    Button {
                        settings.rotateQuarterTurn()
                    } label: {
                        ToolbarTile(title: "Rotate", systemImage: "rotate.right", isActive: false)
                    }
                    .disabled(!settings.hasImage || settings.isLocked || (settings.mode == .ar && !settings.hasPlacement))

                    Button {
                        settings.resetPlacement()
                    } label: {
                        ToolbarTile(title: "Reset", systemImage: "arrow.counterclockwise", isActive: false)
                    }
                    .disabled(!settings.hasImage || settings.isLocked)
                }
                .padding(.horizontal, 2)
            }
        }
        .padding(10)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}
