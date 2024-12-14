// JavaScript for Kachifo with enhanced streaming messages

/**
 * This script handles:
 * 1. Chat bubble creation (including Kachifo logo).
 * 2. Streaming logic for server responses using messages.
 * 3. Smooth animations for user and server messages.
 * 4. Typing indicators and reset functionality.
 * 5. Dynamic suggestions and desktop checks.
 */

document.addEventListener('DOMContentLoaded', () => {
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const chatWindow = document.querySelector('.chat-window');
    const initialView = document.querySelector('.initial-view');
    const suggestions = document.querySelector('.suggestions');
    const newChatIcon = document.querySelector('.new-chat-icon');
    const kachifoLogoPath = '/static/logo/kachifo-logo-small.svg';

    /**
     * Scrolls to the latest message in the chat window.
     */
    const scrollToBottom = () => {
        chatWindow.scrollTop = chatWindow.scrollHeight;
    };

    /**
     * Checks if the user is on a desktop device.
     * @returns {boolean} True if desktop, false otherwise.
     */
    const isDesktop = () => window.innerWidth >= 1024;

    /**
     * Creates a chat bubble for the user or Kachifo.
     * @param {string} sender - 'user' or 'kachifo'.
     * @param {string} message - The message content.
     * @returns {HTMLElement} The created chat bubble element.
     */
    function createChatBubble(sender, message) {
        const bubble = document.createElement('div');
        bubble.classList.add(sender === 'user' ? 'user-message' : 'kachifo-message');

        if (sender === 'kachifo') {
            const logoImg = document.createElement('img');
            logoImg.src = kachifoLogoPath;
            logoImg.alt = 'Kachifo Logo';
            logoImg.classList.add('kachifo-logo-small');
            bubble.appendChild(logoImg);
        }

        const messageContent = document.createElement('div');
        messageContent.classList.add('message-content');
        messageContent.textContent = message;

        bubble.appendChild(messageContent);
        chatWindow.appendChild(bubble);
        scrollToBottom();
        return bubble;
    }

    /**
     * Streams loading messages dynamically.
     * @param {HTMLElement} typingBubble - The typing bubble element to update.
     * @returns {number} Interval ID for clearing the streaming messages.
     */
    function streamLoadingMessages(typingBubble) {
        const loadingMessages = [
            "Fetching data...",
            "Analyzing input...",
            "Compiling results...",
            "Almost there!",
            "Generating insights...",
            "Hang tight!",
            "Preparing a response...",
            "Finalizing the details..."
        ];

        let index = 0;
        const intervalId = setInterval(() => {
            typingBubble.textContent = loadingMessages[index];
            index = (index + 1) % loadingMessages.length;
        }, 2000);

        return intervalId;
    }

    /**
     * Handles server response streaming with dynamic loading messages.
     * @param {string} userMessage - The user's input message.
     */
    function handleStreaming(userMessage) {
        createChatBubble('user', userMessage);

        const typingBubble = createChatBubble('kachifo', 'Fetching data...');
        const loadingInterval = streamLoadingMessages(typingBubble);

        const eventSource = new EventSource(`/stream?input=${encodeURIComponent(userMessage)}`);

        eventSource.onmessage = (event) => {
            if (event.data) {
                try {
                    const data = JSON.parse(event.data);

                    if (data.complete) {
                        clearInterval(loadingInterval);
                        typingBubble.remove();
                        data.response.forEach((messagePart) => {
                            createChatBubble('kachifo', messagePart);
                        });
                        eventSource.close();
                    } else {
                        typingBubble.textContent = data.message;
                    }
                } catch (error) {
                    console.error('Error parsing streaming data:', error);
                    clearInterval(loadingInterval);
                    typingBubble.textContent = 'An error occurred. Please try again later.';
                    eventSource.close();
                }
            }
        };

        eventSource.onerror = () => {
            clearInterval(loadingInterval);
            typingBubble.textContent = 'An error occurred. Please try again later.';
            eventSource.close();
        };
    }

    /**
     * Sends a message to the server and handles the response.
     * @param {string} [message] - The message to send (optional).
     */
    async function sendMessage(message) {
        if (!message) {
            message = userInput.value.trim();
        }
        if (message === '') return;

        handleStreaming(message);
        userInput.value = '';
        userInput.style.height = 'auto';
        initialView.classList.add('hidden');
        suggestions.classList.add('hidden');
        chatWindow.classList.add('active');
    }

    /**
     * Resets the chat window and restores the initial UI.
     */
    function resetChat() {
        chatWindow.innerHTML = '';
        initialView.classList.remove('hidden');
        suggestions.classList.remove('hidden');
        chatWindow.classList.remove('active');
        userInput.value = '';
        attachSuggestionListeners();
    }

    /**
     * Attaches listeners for dynamic suggestions.
     */
    function attachSuggestionListeners() {
        const suggestionElements = document.querySelectorAll('.suggestion');
        suggestionElements.forEach((suggestion) => {
            suggestion.addEventListener('click', () => {
                sendMessage(suggestion.textContent.trim());
            });
        });
    }

    // Event listener for the send button
    sendBtn.addEventListener('click', () => {
        sendMessage();
    });

    // Event listener for pressing "Enter" to send a message
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Event listener for resetting the chat
    newChatIcon.addEventListener('click', resetChat);

    // Attach suggestion listeners on page load
    attachSuggestionListeners();

    // Scroll to the bottom of the chat window on page load
    scrollToBottom();
});
