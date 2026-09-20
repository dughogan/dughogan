import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: OverlaySettings
    @State private var showSettings = false

    var body: some View {
        ZStack {
            switch settings.mode {
            case .ar:
                ARTraceView()
                    .ignoresSafeArea()
            case .tripod:
                TripodOverlayView()
                    .ignoresSafeArea()
            }

            VStack(spacing: 12) {
                topBar
                Spacer()
                if !settings.hasImage {
                    emptyState
                    Spacer()
                }
                if let message = settings.statusMessage {
                    statusPill(message)
                }
                ControlsPanel(showSettings: $showSettings)
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)
            .padding(.bottom, 8)
        }
        .background(Color.black)
        .sheet(isPresented: $showSettings) {
            SettingsSheet()
                .environmentObject(settings)
        }
    }

    private var topBar: some View {
        HStack(spacing: 10) {
            Picker("Mode", selection: $settings.mode) {
                ForEach(ViewMode.allCases) { mode in
                    Label(mode.label, systemImage: mode.systemImage).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 220)

            Spacer()

            Button {
                withAnimation(.snappy) { settings.isLocked.toggle() }
            } label: {
                Image(systemName: settings.isLocked ? "lock.fill" : "lock.open")
                    .font(.system(size: 18, weight: .semibold))
                    .frame(width: 44, height: 44)
            }
            .tint(settings.isLocked ? .orange : .white)
            .background(.ultraThinMaterial, in: Circle())
            .accessibilityLabel(settings.isLocked ? "Unlock overlay" : "Lock overlay")

            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 18, weight: .semibold))
                    .frame(width: 44, height: 44)
            }
            .tint(.white)
            .background(.ultraThinMaterial, in: Circle())
            .accessibilityLabel("Settings")
        }
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            Image(systemName: "paintpalette")
                .font(.system(size: 44, weight: .light))
                .foregroundStyle(.secondary)
            Text("Overlay a reference on your canvas")
                .font(.headline)
            Text("Pick the image you want to transfer. In AR mode, tap your canvas to pin it there and it stays put as you move.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            ImagePickerButton(style: .prominent)
        }
        .padding(24)
        .frame(maxWidth: 340)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private func statusPill(_ message: String) -> some View {
        HStack(spacing: 8) {
            if settings.isProcessing {
                ProgressView()
                    .controlSize(.small)
            }
            Text(message)
                .font(.footnote.weight(.medium))
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial, in: Capsule())
        .transition(.opacity)
        .animation(.easeInOut(duration: 0.2), value: message)
    }
}

#Preview {
    ContentView()
        .environmentObject(OverlaySettings())
}
