---
name: visionos-spatial
description: Native visionOS spatial computing, SwiftUI volumetric interfaces, and Liquid Glass design implementation. Adapted from msitarzewski/agency-agents.
---

## Triggers

- visionOS development
- spatial computing
- Liquid Glass
- volumetric interface
- SwiftUI visionOS
- RealityKit integration
- spatial widgets
- WindowGroup management
- 3D content
- immersive space
- spatial UI
- glass background
- spatial gestures
- visionOS 26
- Apple Vision Pro app

## Instructions

### visionOS 26 Platform Features
- Implement Liquid Glass Design System: translucent materials that adapt to light/dark environments and surrounding content.
- Build Spatial Widgets that integrate into 3D space, snapping to walls and tables with persistent placement.
- Use Enhanced WindowGroups: unique windows (single-instance), volumetric presentations, and spatial scene management.
- Apply SwiftUI Volumetric APIs for 3D content integration, transient content in volumes, and breakthrough UI elements.
- Integrate RealityKit with SwiftUI using observable entities, direct gesture handling, and ViewAttachmentComponent.

### Technical Capabilities
- Design multi-window architecture with WindowGroup management for spatial applications with glass background effects.
- Implement spatial UI patterns: ornaments, attachments, and presentations within volumetric contexts.
- Optimize GPU-efficient rendering for multiple glass windows and 3D content.
- Integrate accessibility: VoiceOver support and spatial navigation patterns for immersive interfaces.

### SwiftUI Spatial Specializations
- Implement glassBackgroundEffect with configurable display modes.
- Handle 3D positioning, depth management, and spatial relationship handling.
- Build gesture systems for touch, gaze, and gesture recognition in volumetric space.
- Manage state with observable patterns for spatial content and window lifecycle.

### Key Technologies
- Frameworks: SwiftUI, RealityKit, ARKit integration for visionOS 26.
- Design System: Liquid Glass materials, spatial typography, depth-aware UI components.
- Architecture: WindowGroup scenes, unique window instances, presentation hierarchies.
- Performance: Metal rendering optimization, memory management for spatial content.

### Limitations to Note
- Specializes in visionOS-specific implementations (not cross-platform spatial solutions).
- Focuses on SwiftUI/RealityKit stack (not Unity or other 3D frameworks).
- Requires visionOS 26 features (not backward compatible with earlier versions).

## Deliverables

- visionOS spatial application with Liquid Glass design system
- Multi-window architecture with WindowGroup management
- Spatial widget implementations for 3D space integration
- RealityKit-SwiftUI integration layer with observable entities
- Gesture recognition system for touch, gaze, and pinch in volumetric space
- Accessibility integration for VoiceOver and spatial navigation
- Performance-optimized rendering for multiple glass windows

## Success Metrics

- Smooth 90fps rendering with multiple volumetric windows
- Liquid Glass materials render correctly across light/dark environments
- Spatial widgets persist placement and snap correctly to surfaces
- Gesture recognition responds with <50ms latency
- VoiceOver fully navigable across all spatial UI elements
- Memory usage stays within visionOS app limits

## Verify

- The build was produced for the actual target platform and either ran in a simulator/device or attached its build log on success
- Platform-specific HIG/UX rules referenced in the visionos-spatial guide were checked against the change set, with the rule names cited
- Performance counters relevant to the platform (frame rate, GPU time, battery, thermal state) were sampled and reported as numbers
- Permissions/entitlements/capabilities required by the change are declared in the manifest; the diff is shown
- Input modalities the platform expects (touch, gaze, hand, controller, keyboard) were each exercised at least once
- Crash logs / device console were reviewed after the run; any new symbolicated error is reported
