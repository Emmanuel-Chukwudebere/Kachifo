// JavaScript for chat interaction and handling API responses

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.getElementById('new-chat-icon');
const loadingGifPath = '/static/icons/typing-gif.gif';
const kachifoLogoPath = '/static/logo/kachifo-logo-small.svg';

// Expanded set of loading messages moved entirely to the frontend
const loadingMessages = [
    "AI is fetching trends for you!",
    "Hold tight! We're gathering data...",
    "Did you know? Honey never spoils.",
    "Fun fact: Octopuses have three hearts.",
    "AI is crunching the latest data—please wait.",
    "Stay tuned! We're compiling the top trends.",
    "Pro tip: Great insights are on the way.",
    "Did you know? Your trends are being curated in real-time."
];

// Helper function: Scroll to the latest message
const scrollToBottom = () => {
    chatWindow.scrollTop = chatWindow.scrollHeight;
};

// Helper function to animate text token-by-token
function animateText(element, text, tokenInterval = 200) {
    element.innerHTML = "";
    const tokens = text.split(" ");
    let index = 0;
    const interval = setInterval(() => {
        if (index < tokens.length) {
            const span = document.createElement('span');
            span.textContent = tokens[index] + " ";
            span.style.opacity = '0';
            span.style.transition = 'opacity 0.5s ease-in';
            element.appendChild(span);
            setTimeout(() => {
                span.style.opacity = '1';
            }, 10);
            index++;
            scrollToBottom();
        } else {
            clearInterval(interval);
        }
    }, tokenInterval);
}

// Function to format messages by embedding URLs as clickable links
function formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return message.replace(urlRegex, (url) => {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">[link]</a>`;
    });
}

// Function to create a chat bubble element for either the user or Kachifo
function createChatBubble(sender, isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add(sender === 'kachifo' ? 'kachifo-message' : 'user-message');
    bubble.setAttribute('aria-live', 'polite');

    if (sender === 'kachifo') {
        const logoImg = document.createElement('img');
        logoImg.src = kachifoLogoPath;
        logoImg.alt = 'Kachifo Logo';
        logoImg.classList.add('kachifo-logo-small');
        bubble.appendChild(logoImg);
    }
    const messageContent = document.createElement('div');
    messageContent.classList.add('message-content');
    if (isTyping) {
        // Optionally display a static loading gif initially
        const loadingGif = document.createElement('img');
        loadingGif.src = loadingGifPath;
        loadingGif.alt = 'Loading...';
        loadingGif.classList.add('loading-gif');
        messageContent.appendChild(loadingGif);
    }
    bubble.appendChild(messageContent);
    chatWindow.appendChild(bubble);
    scrollToBottom();
    return messageContent;
}

// Function to simulate streaming responses by cycling loading messages
// with smooth token-by-token animation, and then animate the final response.
function startStreaming(message, typingBubble) {
    // Cycle through preloaded loading messages every 4 seconds
    let loadingInterval = setInterval(() => {
        const randomMessage = loadingMessages[Math.floor(Math.random() * loadingMessages.length)];
        animateText(typingBubble, randomMessage, 100);
    }, 4000);

    // Fetch the final response from the backend
    fetch('/interact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: message })
    })
    .then(response => response.json())
    .then(data => {
        clearInterval(loadingInterval);
        let displayText = "";
        // Determine response type based on API output
        if (data.response) {
            displayText = data.response;
        } else if (data.general_summary) {
            displayText = data.general_summary;
        }
        // Clear the typing indicator and animate the final response token-by-token
        typingBubble.innerHTML = "";
        animateText(typingBubble, displayText, 200);
    })
    .catch(error => {
        clearInterval(loadingInterval);
        console.error("Error fetching response:", error);
        typingBubble.innerHTML = `<p class="error-message">Error processing response. Please try again.</p>`;
    });
}

// Function to send a message from the user
async function sendMessage(message) {
    if (!message) {
        message = userInput.value.trim();
    }
    if (message === '') return;
    // Display the user's message
    createChatBubble('user').innerHTML = formatMessageWithLinks(message);
    userInput.value = '';
    userInput.style.height = 'auto';
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');
    // Create a bubble for Kachifo's response with a typing indicator
    const typingBubble = createChatBubble('kachifo', true);
    // Start simulated streaming with loading messages until the final response arrives
    startStreaming(message, typingBubble);
}

// Function to reset the chat window for a new conversation
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    userInput.value = '';
    scrollToBottom();
    attachSuggestionListeners();
}

// Dynamically attach listeners to suggestion elements
function attachSuggestionListeners() {
    const suggestionElements = document.querySelectorAll('.suggestion');
    suggestionElements.forEach(suggestion => {
        suggestion.addEventListener('click', handleSuggestionClick);
    });
}

// Handle suggestion click events to auto-send the suggestion text
function handleSuggestionClick(event) {
    const suggestionText = event.target.textContent.trim();
    if (suggestionText) {
        sendMessage(suggestionText);
    }
}

// Attach event listeners on DOMContentLoaded and for button/key events
document.addEventListener('DOMContentLoaded', () => {
    attachSuggestionListeners();
});

sendBtn.addEventListener('click', (e) => {
    e.preventDefault();
    sendMessage();
});

userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && window.innerWidth >= 1024) {
        e.preventDefault();
        sendMessage();
    }
});

// Debounce function for auto-resizing the input field
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

userInput.addEventListener('input', debounce(function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    if (this.value.trim() !== '') {
        initialView.classList.add('typing');
        suggestions.classList.add('typing');
    } else {
        initialView.classList.remove('typing');
        suggestions.classList.remove('typing');
    }
}, 100));

newChatIcon.addEventListener('click', (e) => {
    e.preventDefault();
    resetChat();
});

window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

window.onerror = function(message, source, lineno, colno, error) {
    console.error('Global error:', message, 'at', source, lineno, colno, error);
};