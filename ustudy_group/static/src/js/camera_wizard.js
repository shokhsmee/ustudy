/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { onMounted, onWillUnmount } from "@odoo/owl";

let mediaStream = null;

class CameraWizardFormController extends FormController {
    setup() {
        super.setup();
        
        onMounted(() => {
            this.setupCameraWidget();
        });
        
        onWillUnmount(() => {
            this.stopCamera();
        });
    }

    setupCameraWidget() {
        const self = this;
        const startBtn = document.getElementById('btn_start_camera');
        const captureBtn = document.getElementById('btn_capture_photo');
        const retakeBtn = document.getElementById('btn_retake');
        const startAttendanceBtn = document.getElementById('btn_start_attendance');
        const video = document.getElementById('camera_video');
        const canvas = document.getElementById('camera_canvas');
        const previewDiv = document.getElementById('preview_image');
        const capturedPhoto = document.getElementById('captured_photo');
        const placeholder = document.getElementById('camera_placeholder');

        if (!startBtn || !video || !canvas) {
            console.error('Camera widget elements not found');
            return;
        }

        // Show/hide a footer button reliably. Odoo does not honour the inline
        // `style="display:none"` set in the XML on footer buttons, so every
        // button showed at once (Open Camera / Capture / Retake / Start).
        // We drive visibility from JS instead — with `!important` so nothing
        // in the framework CSS can force a hidden button back on screen.
        const show = (el) => el && el.style.setProperty('display', 'inline-block', 'important');
        const hide = (el) => el && el.style.setProperty('display', 'none', 'important');

        // Initial step: only "Open Camera" (+ the framework Cancel) are usable.
        show(startBtn);
        hide(captureBtn);
        hide(retakeBtn);
        hide(startAttendanceBtn);

        // System admins may start the lesson without a photo (the server makes
        // the photo optional for them on the START wizard only), so surface the
        // "Start" button straight away. is_admin only exists on the START
        // wizard model, so the END wizard (photo required for everyone) is
        // never affected — its value is simply undefined there.
        const rootData = (this.model && this.model.root && this.model.root.data) || {};
        if (rootData.is_admin) {
            show(startAttendanceBtn);
        }

        // Start Camera Button
        if (startBtn) {
            startBtn.onclick = async function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                try {
                    mediaStream = await navigator.mediaDevices.getUserMedia({ 
                        video: { 
                            width: { ideal: 640 },
                            height: { ideal: 480 },
                            facingMode: "user"
                        } 
                    });
                    
                    video.srcObject = mediaStream;
                    video.style.display = 'block';
                    if (placeholder) placeholder.style.display = 'none';
                    if (previewDiv) previewDiv.style.display = 'none';
                    
                    hide(startBtn);
                    show(captureBtn);
                    hide(retakeBtn);
                    hide(startAttendanceBtn);

                } catch (err) {
                    console.error('Camera access error:', err);
                    let errorMsg = 'Camera access denied. ';
                    if (err.name === 'NotAllowedError') {
                        errorMsg += 'Please allow camera access in your browser settings.';
                    } else if (err.name === 'NotFoundError') {
                        errorMsg += 'No camera found on this device.';
                    } else {
                        errorMsg += err.message;
                    }
                    alert(errorMsg);
                }
            };
        }

        // Capture Photo Button
        if (captureBtn) {
            captureBtn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();

                // Guard: the camera must be open and streaming a real frame.
                // Capturing before "Open Camera" gives a 0×0 canvas whose
                // toBlob() returns null — that null was what crashed
                // readAsDataURL with "parameter 1 is not of type 'Blob'".
                if (!mediaStream || !video.videoWidth || !video.videoHeight) {
                    alert("Avval \"Kamerani ochish\" tugmasini bosing.");
                    return;
                }

                const context = canvas.getContext('2d');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                context.drawImage(video, 0, 0);

                canvas.toBlob((blob) => {
                    if (!blob) {
                        alert("Rasmni olishda xatolik yuz berdi. Qayta urinib ko'ring.");
                        return;
                    }
                    const reader = new FileReader();
                    reader.onloadend = function() {
                        const base64Data = reader.result.split(',')[1];

                        // Update the model with the image
                        self.model.root.update({ teacher_image: base64Data });

                        // Show preview
                        capturedPhoto.src = reader.result;
                        previewDiv.style.display = 'block';
                        video.style.display = 'none';

                        // Stop camera
                        self.stopCamera();

                        // Update buttons
                        hide(captureBtn);
                        show(retakeBtn);
                        show(startAttendanceBtn);
                    };
                    reader.readAsDataURL(blob);
                }, 'image/jpeg', 0.85);
            };
        }

        // Retake Button
        if (retakeBtn) {
            retakeBtn.onclick = async function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                try {
                    mediaStream = await navigator.mediaDevices.getUserMedia({ 
                        video: { 
                            width: { ideal: 640 },
                            height: { ideal: 480 },
                            facingMode: "user"
                        } 
                    });
                    
                    video.srcObject = mediaStream;
                    video.style.display = 'block';
                    previewDiv.style.display = 'none';

                    hide(retakeBtn);
                    hide(startAttendanceBtn);
                    show(captureBtn);

                } catch (err) {
                    console.error('Camera access error:', err);
                    alert('Camera access denied: ' + err.message);
                }
            };
        }
    }

    stopCamera() {
        if (mediaStream) {
            mediaStream.getTracks().forEach(track => track.stop());
            mediaStream = null;
        }
    }
}

registry.category("views").add("camera_wizard_form", {
    ...formView,
    Controller: CameraWizardFormController,
});