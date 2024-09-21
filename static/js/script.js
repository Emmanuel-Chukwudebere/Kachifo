// JavaScript for chat interaction
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');
const loadingGifPath = 'static/icons/typing-gif.gif';  // Placeholder for loading gif path
const kachifoLogoPath = 'static/logo/kachifo-logo-small.svg';  // Placeholder for Kachifo logo path

// Function to automatically scroll to the latest message
function scrollToBottom() {
    requestAnimationFrame(() => {
        chatWindow.scrollTop = chatWindow.scrollHeight;  // Force scroll to the bottom
    });
}

// Function to format the message by converting URLs into clickable links
function formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;  // Regular expression to detect URLs
    return message.replace(urlRegex, (url) => {
        return `<a href="${url}" target="_blank">${url}</a>`;
    });
}

// Function to create chat bubbles
function createChatBubble(message, sender, isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add(sender === 'kachifo' ? 'kachifo-message' : 'user-message');

    if (sender === 'kachifo') {
        // Add Kachifo's logo next to the message
        const kachifoLogo = document.createElement('img');
        kachifoLogo.src = kachifoLogoPath;
        kachifoLogo.alt = 'Kachifo Logo';
        kachifoLogo.classList.add('kachifo-logo-small');
        bubble.appendChild(kachifoLogo);
    }

    const messageContent = document.createElement('div');
    messageContent.classList.add('message-content');

    if (isTyping) {
        const loadingGif = document.createElement('img');
        loadingGif.src = loadingGifPath;
        loadingGif.alt = 'Kachifo is typing...';
        loadingGif.classList.add('loading-gif');
        messageContent.appendChild(loadingGif);
    } else {
        // Use formatMessageWithLinks function to replace URLs with clickable links
        messageContent.innerHTML = formatMessageWithLinks(message);
    }

    bubble.appendChild(messageContent);
    chatWindow.appendChild(bubble);

    // Ensure the chat window scrolls to the bottom after the message is added
    scrollToBottom();

    return bubble;
}

// Function to handle sending a message
function sendMessage(message) {
    if (!message) {
        message = userInput.value.trim();
    }
    if (message === '') return;

    // Create user message bubble
    createChatBubble(message, 'user');
    userInput.value = '';
    userInput.style.height = 'auto'; // Reset input field height

    // Hide initial view and show chat window
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');

    // Show typing indicator
    const typingBubble = createChatBubble('', 'kachifo', true);

    // Fetch response from Flask backend
    fetch('/search', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ query: message })
    })
    .then(response => response.json())
    .then(data => {
        typingBubble.remove();
        if (data.response) {
            createChatBubble(data.response, 'kachifo');
        } else if (data.error) {
            createChatBubble(`Error: ${data.error}`, 'kachifo');
        }
    })
    .catch(error => {
        // Handle errors and show an error message
        typingBubble.remove();
        createChatBubble('Something went wrong. Please try again.', 'kachifo');
        console.error('Error:', error);
    });
}

// Function to reset the chat
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    scrollToBottom(); // Scroll to bottom after resetting chat
}

// Function to check if the user is on a desktop
function isDesktop() {
    return window.innerWidth >= 1024;
}

// Event listener for the send button
sendBtn.addEventListener('click', () => sendMessage());

// Event listener for pressing "Enter" key in the input field (only for desktop)
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && isDesktop()) {
        e.preventDefault();
        sendMessage();
    }
});

// Auto-resize input field and handle typing state
userInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';

    if (this.value.trim() !== '') {
        initialView.classList.add('typing');
        suggestions.classList.add('typing');
    } else {
        initialView.classList.remove('typing');
        suggestions.classList.remove('typing');
    }
});

// Event listeners for suggestions
document.querySelectorAll('.suggestion').forEach(suggestion => {
    suggestion.addEventListener('click', () => {
        sendMessage(suggestion.textContent);
    });
});

// Event listener for the New Chat icon
newChatIcon.addEventListener('click', resetChat);

// Initial scroll to bottom on page load
scrollToBottom();
