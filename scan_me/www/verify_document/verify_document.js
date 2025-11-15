document.getElementById("scan_btn").onclick = startScan;

function setResult(type, lines = []) {
    const box = document.getElementById("result_box");
    box.innerHTML = "";

    const div = document.createElement("div");
    div.className = `result ${type}`;
    div.innerHTML = lines.map(l => `<div>${l}</div>`).join("");
    box.appendChild(div);
}

function verifyDocument() {
    const uuid = document.getElementById("uuid_input").value.trim();

    if (!uuid) {
        setResult("error", ["Please enter a UUID."]);
        return;
    }

    fetch(`/api/method/scan_me.api.verified_qr.verify_qr?uuid=${encodeURIComponent(uuid)}`)
        .then(async res => {

            if (res.status === 429) {
                setResult("error", [
                    "<strong>Too Many Requests</strong>",
                    "You have reached the verification limit.",
                    "Please wait a moment before trying again."
                ]);
                throw new Error("Rate limit exceeded");
            }

            return res.json();
        })
        .then(r => {
            const d = r.message || {};

            if (d.status === "valid") {
                setResult("success", [
                    "<strong>Document Authenticated</strong>",
                    "You may continue with the next required step."
                ]);
            } else {
                setResult("error", [
                    "<strong>Unable to Validate</strong>",
                    "The provided QR code is not associated with any approved record.",
                    "Kindly recheck the document and attempt verification again."
                ]);
            }
        })
        .catch(err => {
            console.error(err);
            setResult("error", [
                "Verification service is temporarily unavailable.",
                "Please try again shortly."
            ]);
        });
}

function startScan() {
    const cameraBox = document.getElementById("camera_container");
    cameraBox.innerHTML = "";

    const scanner = new Html5Qrcode("camera_container");

    Html5Qrcode.getCameras()
        .then(cameras => {
            if (!cameras.length) {
                alert("No camera detected.");
                return;
            }

            scanner.start(
                cameras[0].id,
                { fps: 10, qrbox: 250 },
                qrText => {
                    scanner.stop().then(() => {
                        document.getElementById("uuid_input").value = qrText;
                        verifyDocument();
                    });
                },
                err => {
                    console.warn("QR scan error:", err);
                }
            );
        })
        .catch(err => {
            console.error("Camera access error:", err);
            alert("Unable to access camera.");
        });
}
