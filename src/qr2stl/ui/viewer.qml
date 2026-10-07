import QtQuick
import QtQuick3D
import Qr2Stl

// Vista previa 3D. Python asigna las mallas (MeshGeometry) y los colores; acá vive la
// cámara orbital con amortiguación, los presets animados y el HUD.
Item {
    id: root

    // ---- lo que setea Python
    property color bgColor: "#ececec"
    property color fgColor: "#1d1d1f"
    property color accentColor: "#0a84ff"
    property color plateColor: "#f2f2f2"
    property color codeColor: "#1c1c1e"
    property bool dark: false
    property real plateW: 50
    property real plateH: 50
    property real plateT: 2
    property real baseZ: 1.2
    property string stats: ""
    property string dims: ""
    property bool hasModel: false
    property string message: ""
    property bool autoRotate: true

    // ---- cámara: valores objetivo y valores mostrados (se acercan cada cuadro)
    property real yawT: -32
    property real pitchT: -38
    property real distT: fitDistance()
    property real panXT: 0
    property real panYT: 0
    property real yaw: yawT
    property real pitch: pitchT
    property real dist: distT * 1.8
    property real panX: 0
    property real panY: 0
    property real idleFor: 0
    property int preset: 0      // 0 = 3D, 1 = arriba, 2 = frente

    readonly property real span: Math.max(plateW, plateH, 10)

    function fitDistance() {
        var fov = cam.fieldOfView * Math.PI / 180
        var aspect = Math.max(0.3, view.width / Math.max(1, view.height))
        var s = Math.max(plateH, plateW / aspect)
        return (s * 0.5) / Math.tan(fov / 2) * 1.35
    }

    function setView(i) {
        preset = i
        idleFor = 0
        panXT = 0; panYT = 0
        distT = fitDistance()
        // el yaw objetivo se lleva al giro más corto
        var targets = [[-32, -38], [0, -90], [0, -8]]
        var y = targets[i][0]
        while (y - yaw > 180) y -= 360
        while (yaw - y > 180) y += 360
        yawT = y
        pitchT = targets[i][1]
    }

    function refit() { distT = fitDistance() }
    function poke() { idleFor = 0 }

    // Animación de «crecer» del relieve cuando cambia la estructura (marco/texto)
    function pulse() { grow.restart() }

    onPlateWChanged: refitTimer.restart()
    onPlateHChanged: refitTimer.restart()
    Timer { id: refitTimer; interval: 120; onTriggered: root.refit() }

    Rectangle { anchors.fill: parent; color: root.bgColor }

    View3D {
        id: view
        anchors.fill: parent
        camera: cam
        onWidthChanged: refitTimer.restart()
        onHeightChanged: refitTimer.restart()

        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            aoEnabled: true
            aoStrength: 55
            aoDistance: 2.2
            aoSoftness: 40
            aoSampleRate: 3
            tonemapMode: SceneEnvironment.TonemapModeLinear
        }

        Node {
            id: orbit
            position: Qt.vector3d(root.panX, root.panY, 0)
            eulerRotation: Qt.vector3d(root.pitch, root.yaw, 0)
            PerspectiveCamera {
                id: cam
                fieldOfView: 30
                clipNear: 1
                clipFar: 20000
                z: root.dist
            }
        }

        DirectionalLight {
            eulerRotation: Qt.vector3d(-55, -35, 0)
            brightness: 1.25
            ambientColor: root.dark ? Qt.rgba(0.30, 0.30, 0.33, 1) : Qt.rgba(0.42, 0.42, 0.44, 1)
            castsShadow: true
            shadowMapQuality: Light.ShadowMapQualityVeryHigh
            shadowFactor: 60
            softShadowQuality: Light.PCF16
            pcfFactor: 2
            shadowBias: 0.08
            csmNumSplits: 0
            shadowMapFar: root.dist * 3
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-25, 140, 0)
            brightness: 0.35
        }

        // Mesa (Y arriba en Quick3D; el modelo viene en Z arriba)
        Model {
            source: "#Rectangle"
            eulerRotation.x: -90
            y: -0.02
            scale: Qt.vector3d(root.span * 0.06, root.span * 0.06, 1)
            receivesShadows: true
            castsShadows: false
            materials: PrincipledMaterial {
                baseColor: root.dark ? Qt.darker(root.bgColor, 1.25) : Qt.darker(root.bgColor, 1.06)
                roughness: 0.9
                lighting: PrincipledMaterial.FragmentLighting
            }
        }
        Model {
            geometry: gridGeo
            eulerRotation.x: -90
            y: 0.01
            castsShadows: false
            receivesShadows: false
            materials: PrincipledMaterial {
                baseColor: Qt.rgba(root.fgColor.r, root.fgColor.g, root.fgColor.b, 1)
                opacity: root.dark ? 0.10 : 0.08
                lighting: PrincipledMaterial.NoLighting
                alphaMode: PrincipledMaterial.Blend
            }
        }

        Node {
            id: part
            eulerRotation.x: -90
            position: Qt.vector3d(-root.plateW / 2, 0, root.plateH / 2)
            opacity: root.hasModel ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }

            Model {
                geometry: plateGeo
                castsShadows: true
                receivesShadows: true
                materials: PrincipledMaterial {
                    baseColor: root.plateColor
                    roughness: 0.62
                    specularAmount: 0.35
                }
            }
            Node {
                id: raised
                z: root.baseZ
                Model {
                    geometry: codeGeo
                    castsShadows: true
                    receivesShadows: true
                    materials: PrincipledMaterial {
                        baseColor: root.codeColor
                        roughness: 0.5
                        specularAmount: 0.4
                    }
                }
            }
        }

        MeshGeometry { id: plateGeo; objectName: "plateGeo" }
        MeshGeometry { id: codeGeo; objectName: "codeGeo" }
        MeshGeometry { id: gridGeo; objectName: "gridGeo" }
    }

    SequentialAnimation {
        id: grow
        NumberAnimation { target: raised; property: "scale.z"; to: 0.05; duration: 90; easing.type: Easing.InCubic }
        NumberAnimation { target: raised; property: "scale.z"; to: 1.0; duration: 520; easing.type: Easing.OutBack; easing.overshoot: 2.2 }
    }

    // Cada cuadro: amortiguación exponencial hacia los objetivos + giro automático
    FrameAnimation {
        running: true
        onTriggered: {
            var dt = Math.min(frameTime, 0.05)
            root.idleFor += dt
            if (root.autoRotate && root.preset === 0 && root.idleFor > 4 && !drag.active)
                root.yawT += dt * 6 * Math.min(1, (root.idleFor - 4) / 2)
            var k = 1 - Math.exp(-dt * 10)
            root.yaw += (root.yawT - root.yaw) * k
            root.pitch += (root.pitchT - root.pitch) * k
            root.dist += (root.distT - root.dist) * (1 - Math.exp(-dt * 7))
            root.panX += (root.panXT - root.panX) * k
            root.panY += (root.panYT - root.panY) * k
        }
    }

    // ---- interacción
    DragHandler {
        id: drag
        target: null
        acceptedButtons: Qt.LeftButton
        property point last
        onActiveChanged: { last = centroid.position; root.poke() }
        onCentroidChanged: {
            if (!active) return
            var d = Qt.point(centroid.position.x - last.x, centroid.position.y - last.y)
            last = centroid.position
            root.preset = -1
            root.idleFor = 0
            root.yawT -= d.x * 0.35
            root.pitchT = Math.max(-90, Math.min(5, root.pitchT - d.y * 0.35))
        }
    }
    DragHandler {
        id: pan
        target: null
        acceptedButtons: Qt.RightButton | Qt.MiddleButton
        property point last
        onActiveChanged: { last = centroid.position; root.poke() }
        onCentroidChanged: {
            if (!active) return
            var d = Qt.point(centroid.position.x - last.x, centroid.position.y - last.y)
            last = centroid.position
            var s = root.dist / Math.max(1, view.height) * 0.55
            var r = root.yaw * Math.PI / 180
            root.panXT -= (d.x * Math.cos(r)) * s
            root.panYT += d.y * s
        }
    }
    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: (event) => {
            root.poke()
            var delta = event.angleDelta.y !== 0 ? event.angleDelta.y : event.pixelDelta.y * 3
            var f = Math.pow(0.999, delta)
            root.distT = Math.max(root.span * 0.6, Math.min(root.span * 12, root.distT * f))
        }
    }
    PinchHandler {
        target: null
        property real start
        onActiveChanged: start = root.distT
        onActiveScaleChanged: root.distT = Math.max(root.span * 0.6, Math.min(root.span * 12, start / activeScale))
    }
    TapHandler {
        acceptedButtons: Qt.LeftButton
        onDoubleTapped: root.setView(0)
    }

    // ---- HUD
    component Glass: Rectangle {
        radius: 10
        color: root.dark ? Qt.rgba(0.17, 0.17, 0.18, 0.78) : Qt.rgba(1, 1, 1, 0.78)
        border.width: 1
        border.color: root.dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(0, 0, 0, 0.08)
    }

    Glass {
        id: info
        x: 16; y: 16
        width: infoCol.implicitWidth + 24
        height: infoCol.implicitHeight + 18
        opacity: root.hasModel && root.stats !== "" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
        Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Column {
            id: infoCol
            x: 12; y: 9
            spacing: 2
            Text { text: root.dims; color: root.fgColor; font.pixelSize: 13; font.weight: Font.DemiBold }
            Text { text: root.stats; color: root.fgColor; opacity: 0.6; font.pixelSize: 11 }
        }
    }

    Glass {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 18
        width: bar.implicitWidth + 8
        height: 34
        radius: 17
        Rectangle {
            id: pill
            property Item target: bar.children[Math.max(0, root.preset)]
            visible: root.preset >= 0
            x: 4 + (target ? target.x : 0)
            width: target ? target.width : 0
            y: 4; height: 26; radius: 13
            color: root.accentColor
            Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
        }
        Row {
            id: bar
            x: 4; y: 4
            Repeater {
                model: ["3D", "Arriba", "Frente"]
                delegate: Item {
                    width: lbl.implicitWidth + 26; height: 26
                    Text {
                        id: lbl
                        anchors.centerIn: parent
                        text: modelData
                        font.pixelSize: 12
                        font.weight: root.preset === index ? Font.DemiBold : Font.Normal
                        color: root.preset === index ? "white" : root.fgColor
                        Behavior on color { ColorAnimation { duration: 200 } }
                    }
                    HoverHandler { id: hv; cursorShape: Qt.PointingHandCursor }
                    Rectangle {
                        anchors.fill: parent; radius: 13
                        color: root.fgColor
                        opacity: hv.hovered && root.preset !== index ? 0.07 : 0
                        Behavior on opacity { NumberAnimation { duration: 150 } }
                    }
                    TapHandler { onTapped: root.setView(index) }
                }
            }
            Item {
                width: 34; height: 26
                Text {
                    anchors.centerIn: parent
                    text: "↻"
                    font.pixelSize: 15
                    color: root.autoRotate ? root.accentColor : root.fgColor
                    opacity: root.autoRotate ? 1 : 0.5
                    Behavior on color { ColorAnimation { duration: 200 } }
                    rotation: root.autoRotate ? 360 : 0
                    Behavior on rotation { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: { root.autoRotate = !root.autoRotate; root.poke() } }
            }
        }
    }

    Text {
        anchors.centerIn: parent
        width: parent.width * 0.6
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: root.message
        color: root.fgColor
        opacity: root.message !== "" ? 0.55 : 0
        font.pixelSize: 15
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }

    Text {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        text: "arrastrá para girar · rueda para zoom · doble clic para centrar"
        color: root.fgColor
        opacity: !drag.active && root.idleFor > 1.5 && root.idleFor < 9 ? 0.4 : 0
        font.pixelSize: 10
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }
}
