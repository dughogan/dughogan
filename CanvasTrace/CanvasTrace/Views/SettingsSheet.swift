import SwiftUI

struct SettingsSheet: View {
    @EnvironmentObject private var settings: OverlaySettings
    @Environment(\.dismiss) private var dismiss

    private static let widthFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 1
        formatter.minimum = 1
        return formatter
    }()

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Units", selection: $settings.lengthUnit) {
                        ForEach(LengthUnit.allCases) { unit in
                            Text(unit.label).tag(unit)
                        }
                    }
                    .pickerStyle(.segmented)

                    HStack {
                        Text("Canvas width")
                        Spacer()
                        TextField(
                            "Width",
                            value: Binding(
                                get: { settings.canvasWidthInSelectedUnit },
                                set: { settings.canvasWidthInSelectedUnit = $0 }
                            ),
                            formatter: Self.widthFormatter
                        )
                        .keyboardType(.decimalPad)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 90)
                        Text(settings.lengthUnit.label)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Canvas size")
                } footer: {
                    Text("In AR mode the image is placed at this real-world width so it matches your canvas. The height follows the image's aspect ratio. You can still pinch to fine-tune.")
                }

                Section {
                    Toggle("Hand occlusion", isOn: $settings.handOcclusion)
                    Stepper("Grid: \(settings.gridDivisions) × \(settings.gridDivisions)", value: $settings.gridDivisions, in: 2...12)
                } header: {
                    Text("Overlay")
                } footer: {
                    Text("Hand occlusion lets your hand and brush appear in front of the overlay in AR mode, so you can see your strokes. Turn it off on older phones if the edges flicker.")
                }

                Section("How to use") {
                    Label("Pick the reference image you want to transfer.", systemImage: "1.circle")
                    Label("AR mode: point the phone at your canvas and tap it. The image is pinned there and stays aligned as you move.", systemImage: "2.circle")
                    Label("Drag, pinch and twist to line up the corners. Then lock it.", systemImage: "3.circle")
                    Label("Use Sketch or Values to see edges and value blocks. Turn on the grid to transfer proportions by eye.", systemImage: "4.circle")
                    Label("Tripod mode keeps the image fixed on screen. Use it with the phone on a stand for a rock-steady overlay.", systemImage: "5.circle")
                }
                .font(.footnote)
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
