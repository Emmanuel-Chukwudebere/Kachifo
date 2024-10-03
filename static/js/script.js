// JavaScript for chat interaction and handling API responses with all necessary improvements

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');
const loadingGifPath = 'static/icons/typing-gif.gif';
const kachifoLogoPath = 'static/logo/kachifo-logo-small.svg';
const loadingSpinner = document.getElementById('loading-spinner');

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

    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return displayMessage.replace(urlRegex, (url) => {
        const encodedUrl = encodeURI(url);
        return `<a href="${encodedUrl}" target="_blank" rel="noopener noreferrer">${encodedUrl}</a>`;
    });
}

// Function to create chat bubbles
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
        messageContent.innerHTML = formatMessageWithLinks(message);
    }

    bubble.appendChild(messageContent);
    chatWindow.appendChild(bubble);
    scrollToBottom();
    return bubble;
}

// Function to handle sending a message
async function sendMessage(message) {
    if (!message) {
        message = userInput.value.trim();
    }
    if (message === '') return;

    console.log('Sending query:', { query: message });
    createChatBubble(message, 'user');
    userInput.value = '';
    userInput.style.height = 'auto';
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');

    // Show loading spinner and typing indicator
    loadingSpinner.style.display = 'block';
    const typingBubble = createChatBubble('', 'kachifo', true);

    try {
        const response = await fetch('/process-query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ q: message }),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        typingBubble.remove();

        // Display the results returned by the API
        if (data.data && data.data.general_summary && data.data.dynamic_response && data.data.results) {
            let combinedResponse = `${data.data.general_summary} ${data.data.dynamic_response}`;

            // Iterate over results and append to the response
            data.data.results.forEach(item => {
                combinedResponse += `<br><br>I found a result: <strong>${item.title}</strong>. ${item.summary} <a href="${item.url}" target="_blank">Read more</a>`;
            });

            createChatBubble(combinedResponse, 'kachifo');
        } else if (data.error) {
            createChatBubble(`I'm sorry, but there was an error: ${data.error}`, 'kachifo');
        } else {
            createChatBubble("Something went wrong. Please try again.", 'kachifo');
        }

    } catch (error) {
        console.error('Error:', error);
        typingBubble.remove();
        createChatBubble("Sorry, something went wrong. Let's try that again!", 'kachifo');
    } finally {
        loadingSpinner.style.display = 'none'; // Hide loading spinner when processing is done
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
sendBtn.addEventListener('click', () => {
    sendMessage();
});

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