---
name: terminal-integration
description: Terminal emulation, text rendering optimization, and SwiftTerm integration for modern Swift applications on Apple platforms. Adapted from msitarzewski/agency-agents.
---

## Triggers

- terminal emulation
- SwiftTerm
- terminal rendering
- ANSI escape sequences
- VT100
- terminal integration
- SSH terminal
- terminal performance
- scrollback buffer
- terminal accessibility
- terminal theming
- terminal input handling
- iOS terminal
- macOS terminal
- visionOS terminal

## Instructions

### Terminal Emulation
- Implement complete VT100/xterm ANSI escape sequence support, cursor control, and terminal state management.
- Support UTF-8 and Unicode with proper rendering of international characters and emojis.
- Handle terminal modes: raw mode, cooked mode, and application-specific terminal behavior.
- Implement efficient scrollback buffer management for large terminal histories with search capabilities.

### SwiftTerm Integration
- Embed SwiftTerm views in SwiftUI applications with proper lifecycle management.
- Handle keyboard input processing, special key combinations, and paste operations.
- Implement text selection handling, clipboard integration, and accessibility support.
- Configure font rendering, color schemes, cursor styles, and theme management.

### Performance Optimization
- Optimize Core Graphics text rendering for smooth scrolling and high-frequency text updates.
- Implement efficient buffer handling for large terminal sessions without memory leaks.
- Use proper background processing for terminal I/O without blocking UI updates.
- Optimize rendering cycles and reduce CPU usage during idle periods for battery efficiency.

### SSH Integration Patterns
- Bridge SSH streams to terminal emulator input/output efficiently.
- Handle terminal behavior during connection, disconnection, and reconnection scenarios.
- Display connection errors, authentication failures, and network issues in terminal.
- Manage multiple terminal sessions, window management, and state persistence.

### Technical Capabilities
- SwiftTerm API mastery and customization.
- Terminal protocol specifications and edge cases.
- VoiceOver support, dynamic type, and assistive technology integration.
- Cross-platform considerations for iOS, macOS, and visionOS terminal rendering.

### Key Technologies
- Primary: SwiftTerm library (MIT license)
- Rendering: Core Graphics, Core Text
- Input Systems: UIKit/AppKit input handling and event processing
- Networking: Integration with SSH libraries (SwiftNIO SSH, NMSSH)

## Deliverables

- SwiftTerm-based terminal emulator with full VT100/xterm support
- SwiftUI integration layer with proper lifecycle management
- SSH stream bridging for remote terminal sessions
- Theme engine for font, color scheme, and cursor customization
- Performance-optimized rendering pipeline for high-frequency updates
- Accessibility integration (VoiceOver, dynamic type)
- Multi-session terminal management system

## Success Metrics

- Complete ANSI escape sequence coverage for VT100/xterm standards
- Smooth scrolling at 60fps during high-frequency text output
- Zero memory leaks during extended terminal sessions
- Responsive keyboard input with no perceptible lag
- VoiceOver compatibility for all terminal content
- Cross-platform support for iOS, macOS, and visionOS
