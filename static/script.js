// ===============================
// LifeLine AI - Premium Script
// ===============================

// -------------------------------
// Dark Mode
// -------------------------------

const darkBtn = document.getElementById("darkModeBtn");

if (darkBtn) {
    darkBtn.addEventListener("click", () => {
        document.body.classList.toggle("dark");
    });
}

// -------------------------------
// Auto Scroll Chat
// -------------------------------

const chatBox = document.querySelector(".chat-box");

if (chatBox) {
    chatBox.scrollTop = chatBox.scrollHeight;
}

// -------------------------------
// Voice Recognition
// -------------------------------

const voiceBtn = document.querySelector(".voice-btn");
const input = document.querySelector("input[name='question']");

if ("webkitSpeechRecognition" in window && voiceBtn) {

    const recognition = new webkitSpeechRecognition();

    recognition.lang = "en-US";

    recognition.onresult = function(event) {

        input.value = event.results[0][0].transcript;

    };

    voiceBtn.addEventListener("click", () => {

        recognition.start();

    });

}

// -------------------------------
// SOS Button
// -------------------------------

const sosBtn = document.querySelector(".sos");

if (sosBtn) {

    sosBtn.addEventListener("click", () => {

        alert(
`🚨 EMERGENCY

1. Call Ambulance

2. Stay Calm

3. Give First Aid

4. Contact Family`
        );

    });

}

// -------------------------------
// Nearby Hospitals
// -------------------------------

const hospitalBtn = document.querySelector(".hospital-btn");

if (hospitalBtn) {

    hospitalBtn.addEventListener("click", () => {

        window.open(
"https://www.google.com/maps/search/hospitals+near+me"
        );

    });

}

// -------------------------------
// Typing Animation
// -------------------------------

const ai = document.querySelector(".ai-message");

if (ai) {

    ai.style.opacity = "0";

    setTimeout(() => {

        ai.style.transition = "0.5s";

        ai.style.opacity = "1";

    },500);

}

// -------------------------------
// Image Upload Preview
// -------------------------------

const imageInput = document.getElementById("imageInput");

if(imageInput){

imageInput.addEventListener("change",function(){

alert("📷 Image Selected Successfully");

});

}

// -------------------------------
// Quick Buttons
// -------------------------------

if (input) {
    document.querySelectorAll(".quick").forEach(button => {
        button.addEventListener("click", () => {
            input.value = button.innerText + " First Aid";
        });
    });
}

// -------------------------------
// Welcome
// -------------------------------

console.log("🚑 LifeLine AI Loaded Successfully");