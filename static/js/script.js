// JavaScript for chat interaction and handling API responses with all necessary improvements

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');
const loadingSpinner = document.getElementById('loading-spinner'); // Loading spinner element

const loadingGifPath = 'static/icons/typing-gif.gif'; // Path to loading GIF
const kachifoLogoPath = 'static/logo/kachifo-logo-small.svg'; // Ensure this path is correct

// Debounce function to limit the rate of function calls
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

// Function to automatically scroll to the latest message
const scrollToBottom = debounce(() => {
    chatWindow.scrollTop = chatWindow.scrollHeight;
}, 100);

// Function to format the message by converting URLs into clickable links
function formatMessageWithLinks(message) {
    const MAX_LENGTH = 2000; // Set a limit for message length

    // Truncate the message if it exceeds the limit
    let displayMessage = message.length > MAX_LENGTH ? message.slice(0, MAX_LENGTH) + '... [Read More]' : message;

    // Regular expression to match URLs
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    
    // Replace URLs with clickable <a> links
    return displayMessage.replace(urlRegex, (url) => {
        const encodedUrl = encodeURI(url); // Encode the URL to ensure proper formatting
        return `<a href="${encodedUrl}" target="_blank" rel="noopener noreferrer">${encodedUrl}</a>`;
    });
}

// Function to create chat bubbles, including Kachifo logo
function createChatBubble(message, sender, isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add(sender === 'kachifo' ? 'kachifo-message' : 'user-message');
    bubble.setAttribute('aria-live', 'polite');

    // Add Kachifo logo only for Kachifo messages
    if (sender === 'kachifo' && !isTyping) {
        const kachifoLogo = document.createElement('img');
        kachifoLogo.src = kachifoLogoPath; // Ensure the logo path is correct
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
        messageContent.innerHTML = formatMessageWithLinks(message); // Format message with links
    }

    bubble.appendChild(messageContent);
    chatWindow.appendChild(bubble);
    scrollToBottom();
}

// Function to handle sending a message
async function sendMessage() {
    const message = userInput.value.trim();
    if (message === '') return;

    console.log('Search initiated:', message); // Log the user's query
    createChatBubble(message, 'user');
    userInput.value = '';
    loadingSpinner.style.display = 'block'; // Show loading spinner

    const typingBubble = createChatBubble('', 'kachifo', true);
    try {
        const response = await fetch('/process-query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ q: message }),
        });

        console.log('Response status:', response.status); // Log the response status
        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }

        const data = await response.json();
        typingBubble.remove();

        // Process response
        if (data.data) {
            createChatBubble(data.data.dynamic_response, 'kachifo');
            // Handle additional processing of results and summaries...
        } else if (data.error) {
            createChatBubble(data.error, 'kachifo');
        } else {
            createChatBubble("Unexpected response format.", 'kachifo');
        }
    } catch (error) {
        console.error('Error:', error);
        typingBubble.remove();
        createChatBubble("I'm sorry, something went wrong on my end.", 'kachifo');
    } finally {
        loadingSpinner.style.display = 'none'; // Hide loading spinner when processing is complete
    }
}

// Function to reset the chat
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    scrollToBottom();
}

// Function to check if the user is on a desktop
function isDesktop() {
    return window.innerWidth >= 1024;
}

// Event listener for the send button
sendBtn.addEventListener('click', sendMessage);

// Event listener for pressing "Enter" key in the input field (only for desktop)
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && isDesktop()) {
        e.preventDefault();
        sendMessage();
    }
});

// Auto-resize input field and handle typing state
userInput.addEventListener('input', debounce(function () {
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

// Error handling for unhandled promise rejections
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});