/**
 * Kachifo Chat Interface
 * This script handles user interactions, message streaming, and animations for the Kachifo chat application.
 * It implements client-side streaming simulation and smooth transitions between messages.
 */

// Wait for DOM to be fully loaded before initializing
document.addEventListener('DOMContentLoaded', () => {
  initApplication();
});

function initApplication() {
  // DOM element references - moved inside initialization to ensure DOM is ready
  const elements = {
    userInput: document.getElementById('user-input'),
    sendBtn: document.getElementById('send-btn'),
    chatWindow: document.querySelector('.chat-window'),
    initialView: document.querySelector('.initial-view'),
    suggestions: document.querySelector('.suggestions'),
    newChatIcon: document.querySelector('.new-chat-icon')
  };

  // Log which elements were found/not found for debugging
  console.log("DOM Elements initialized:", 
    Object.entries(elements).map(([key, el]) => 
      `${key}: ${el ? "✓" : "✗"}`).join(', ')
  );

  // Asset paths
  const ASSETS = {
    loadingGif: '/static/icons/typing-gif.gif',
    kachifoLogo: '/static/logo/kachifo-logo-small.svg'
  };

  // Configuration options
  const CONFIG = {
    animationSpeed: 30,     // ms between tokens during text animation
    loadingInterval: 3000,  // ms between loading messages
    typingInterval: 100,    // ms for debouncing resize events
    maxWordDelay: 80        // ms maximum random delay between words
  };

  // Enhanced collection of loading/streaming messages with categories
  const STREAMING_MESSAGES = {
    waiting: [
      "AI is fetching trends for you!",
      "Hold tight! We're gathering data...",
      "Compiling the latest information for you..."
    ],
    facts: [
      "Did you know? Honey never spoils.",
      "Fun fact: Octopuses have three hearts.",
      "The Eiffel Tower can be 15 cm taller during summer due to thermal expansion."
    ],
    processing: [
      "AI is crunching the latest data—please wait.",
      "Stay tuned! We're compiling the top trends.",
      "Analyzing online conversations to find what's trending..."
    ],
    tips: [
      "Pro tip: Great insights are on the way.",
      "Your trends are being curated in real-time.",
      "For best results, try asking about specific topics or industries."
    ]
  };

  /**
   * Scroll chat window to the bottom, showing the latest message
   * Uses requestAnimationFrame for smooth scrolling
   */
  const scrollToBottom = () => {
    if (!elements.chatWindow) return;
    
    requestAnimationFrame(() => {
      elements.chatWindow.scrollTop = elements.chatWindow.scrollHeight;
    });
  };

  /**
   * Format message text by converting URLs to clickable links
   * @param {string} message - Raw message text
   * @return {string} HTML formatted message with clickable links
   */
  const formatMessageWithLinks = (message) => {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return message.replace(urlRegex, (url) => 
      `<a href="${url}" target="_blank" rel="noopener noreferrer" class="message-link">[link]</a>`
    );
  };

  /**
   * Remove any Kachifo prefix from the response
   * @param {string} text - Response text 
   * @returns {string} - Cleaned response text
   */
  const removeKachifoPrefix = (text) => {
    if (!text) return text;
    // Remove prefixes like "Kachifo:", "As Kachifo,", etc.
    return text.replace(/^(Kachifo:|As Kachifo,|I am Kachifo,|I'm Kachifo,)\s*/i, '');
  };

  /**
   * Create a chat bubble for user or Kachifo messages
   * @param {string} sender - 'user' or 'kachifo'
   * @param {boolean} isTyping - Whether to show typing animation
   * @returns {HTMLElement} The message content element for further manipulation
   */
  const createChatBubble = (sender, isTyping = false) => {
    if (!elements.chatWindow) return document.createElement('div'); // Fallback if chatWindow not found
    
    const bubble = document.createElement('div');
    bubble.classList.add(`${sender}-message`);
    bubble.setAttribute('aria-live', sender === 'kachifo' ? 'polite' : 'off');
    
    if (sender === 'kachifo') {
      const logoImg = document.createElement('img');
      logoImg.src = ASSETS.kachifoLogo;
      logoImg.alt = 'Kachifo Logo';
      logoImg.classList.add('kachifo-logo-small');
      bubble.appendChild(logoImg);
    }
    
    const messageContent = document.createElement('div');
    messageContent.classList.add('message-content');
    
    if (isTyping) {
      const loadingGif = document.createElement('img');
      loadingGif.src = ASSETS.loadingGif;
      loadingGif.alt = 'Loading...';
      loadingGif.classList.add('loading-gif');
      messageContent.appendChild(loadingGif);
    }
    
    bubble.appendChild(messageContent);
    elements.chatWindow.appendChild(bubble);
    
    scrollToBottom();
    return messageContent;
  };

  /**
   * Animate text with a natural typing effect
   * @param {HTMLElement} element - Target element to append text
   * @param {string} text - Text to animate
   * @param {number} baseSpeed - Base speed for animation (ms)
   * @returns {Promise} Resolves when animation completes
   */
  const animateText = (element, text, baseSpeed = CONFIG.animationSpeed) => {
    if (!element) return Promise.resolve(); // Safety check
    
    return new Promise((resolve) => {
      element.innerHTML = "";
      const words = text.split(" ");
      let index = 0;
      
      // Function to add the next word with slight random timing variations
      const addNextWord = () => {
        if (index >= words.length) {
          resolve();
          return;
        }
        
        const span = document.createElement('span');
        span.textContent = words[index] + " ";
        span.style.opacity = '0';
        span.style.transform = 'translateY(5px)';
        span.style.transition = 'opacity 0.3s ease-in, transform 0.3s ease-out';
        element.appendChild(span);
        
        // Trigger animation with slight delay for smooth browser rendering
        setTimeout(() => {
          span.style.opacity = '1';
          span.style.transform = 'translateY(0)';
        }, 10);
        
        index++;
        scrollToBottom();
        
        // Add randomness to typing speed for natural effect
        const randomDelay = Math.floor(Math.random() * CONFIG.maxWordDelay) + baseSpeed;
        setTimeout(addNextWord, randomDelay);
      };
      
      addNextWord();
    });
  };

  /**
   * Get a random streaming message from a specific category or any category
   * @param {string} category - Optional category to select from
   * @returns {string} A random message
   */
  const getRandomStreamingMessage = (category = null) => {
    if (category && STREAMING_MESSAGES[category]) {
      const messages = STREAMING_MESSAGES[category];
      return messages[Math.floor(Math.random() * messages.length)];
    }
    
    // If no category specified, pick from any category
    const categories = Object.keys(STREAMING_MESSAGES);
    const randomCategory = categories[Math.floor(Math.random() * categories.length)];
    const messages = STREAMING_MESSAGES[randomCategory];
    return messages[Math.floor(Math.random() * messages.length)];
  };

  /**
   * Simulate streaming responses with loading messages then animate final response
   * @param {string} message - User's message to send to backend
   * @param {HTMLElement} typingBubble - Element to show typing indicators
   */
  const startStreaming = (message, typingBubble) => {
    if (!typingBubble) return; // Safety check
    
    let currentStreamingCategory = 'waiting';
    let streamingCounter = 0;
    
    // Start with a waiting message immediately
    animateText(typingBubble, getRandomStreamingMessage('waiting'), 20);
    
    // Rotate through categories for a more engaging experience
    const loadingInterval = setInterval(() => {
      streamingCounter++;
      
      // Cycle through categories based on counter
      if (streamingCounter % 4 === 1) currentStreamingCategory = 'facts';
      else if (streamingCounter % 4 === 2) currentStreamingCategory = 'processing';
      else if (streamingCounter % 4 === 3) currentStreamingCategory = 'tips';
      else currentStreamingCategory = 'waiting';
      
      animateText(typingBubble, getRandomStreamingMessage(currentStreamingCategory), 20);
    }, CONFIG.loadingInterval);
    
    // Send actual request to backend
    fetch('/interact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        input: message,
        session_id: sessionStorage.getItem('session_id') || ''
      })
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`Server responded with status: ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      clearInterval(loadingInterval);
      
      // Save session_id if provided
      if (data.session_id) {
        sessionStorage.setItem('session_id', data.session_id);
      }
      
      // Remove loading indicators
      typingBubble.innerHTML = "";
      
      // Determine how to display the response based on its type
      if (data.type === 'query' || data.type === 'web_search' || (data.results && data.results.length > 0)) {
        // For search results and web search, use the special formatting
        const resultsDisplay = formatResultsForDisplay(data);
        animateText(typingBubble, resultsDisplay);
      } 
      else if (data.type === 'analysis' && data.analysis) {
        // For analysis responses
        animateText(typingBubble, data.analysis);
      }
      else if (data.response) {
        // For conversation responses
        animateText(typingBubble, data.response);
      }
      else {
        // Fallback for any other response format
        const displayText = data.general_summary || data.summary || 
                           data.analysis || data.response || 
                           "I processed your request but have no specific information to return.";
        animateText(typingBubble, displayText);
      }
    })
    .catch(error => {
      clearInterval(loadingInterval);
      console.error("Error fetching response:", error);
      typingBubble.innerHTML = `
        <p class="error-message">
          Sorry, I couldn't process that request. Please try again.
          <span class="error-details">${error.message}</span>
        </p>`;
    });
  };

  /**
   * Format search results for display in chat
   * @param {Object} data - Response data containing results
   * @returns {string} Formatted HTML string
   */
  const formatResultsForDisplay = (data) => {
    if (!data.results || data.results.length === 0) {
      const response = data.general_summary || data.response || "No results found for your query.";
      return removeKachifoPrefix(response);
    }
    
    // Start with the general summary or analysis text if available
    let formattedText = "";
    if (data.general_summary) {
      formattedText += `${removeKachifoPrefix(data.general_summary)}\n\n`;
    } else if (data.analysis) {
      formattedText += `${removeKachifoPrefix(data.analysis)}\n\n`;
    } else if (data.response) {
      formattedText += `${removeKachifoPrefix(data.response)}\n\n`;
    } else {
      formattedText += `Here's what I found about '${data.query || "your topic"}':\n\n`;
    }
    
    // Add detailed results
    formattedText += `DETAILED RESULTS:\n`;
    
    data.results.forEach((result, index) => {
      const sourceLabel = result.source ? ` (${result.source})` : '';
      formattedText += `${index + 1}. ${result.title}${sourceLabel}\n`;
      
      // Include summary if available
      if (result.summary && result.summary.trim() !== '') {
        formattedText += `   ${result.summary}\n`;
      } else if (result.snippet && result.snippet.trim() !== '') {
        formattedText += `   ${result.snippet}\n`;
      }
      
      // Always include URL if available
      if (result.url) {
        formattedText += `   Link: ${result.url}\n`;
      } else if (result.link) {
        formattedText += `   Link: ${result.link}\n`;
      }
      
      formattedText += '\n';
    });
    
    return formattedText;
  };

  /**
   * Send a message from the user
   * @param {string} message - Optional message text (defaults to input field value)
   */
  const sendMessage = (message = '') => {
    // Safety checks for required elements
    if (!elements.chatWindow) {
      console.error("Chat window element not found");
      return;
    }
    
    let messageText = message;
    
    if (!messageText && elements.userInput) {
      messageText = elements.userInput.value.trim();
    }
    
    if (!messageText) return;
    
    // Create user message bubble
    createChatBubble('user').innerHTML = formatMessageWithLinks(messageText);
    
    // Reset input field
    if (elements.userInput) {
      elements.userInput.value = '';
      elements.userInput.style.height = 'auto';
    }
    
    // Hide initial elements, show chat
    if (elements.initialView) elements.initialView.classList.add('hidden');
    if (elements.suggestions) elements.suggestions.classList.add('hidden');
    if (elements.chatWindow) elements.chatWindow.classList.add('active');
    
    // Create and start loading animation for Kachifo's response
    const typingBubble = createChatBubble('kachifo', true);
    startStreaming(messageText, typingBubble);
  };

  /**
   * Reset the chat to initial state
   * Clears conversation and shows initial view
   */
  const resetChat = () => {
    // Clear the chat window
    if (elements.chatWindow) {
      elements.chatWindow.innerHTML = '';
      elements.chatWindow.classList.remove('active');
    }
    
    // Show initial view
    if (elements.initialView) {
      elements.initialView.style.display = 'flex';
      elements.initialView.classList.remove('hidden');
      
      // Use a timeout to trigger fade-in animation
      setTimeout(() => {
        elements.initialView.style.opacity = '1';
        elements.initialView.style.transform = 'translateY(0)';
      }, 10);
    }
    
    // Show suggestions
    if (elements.suggestions) {
      elements.suggestions.classList.remove('hidden');
      
      // Reset the state to display the suggestions
      setTimeout(() => {
        elements.suggestions.style.opacity = '1';
        elements.suggestions.style.transform = 'translateY(0)';
      }, 10);
    }
    
    // Clear the user input
    if (elements.userInput) {
      elements.userInput.value = '';
      elements.userInput.style.height = '';
      elements.userInput.focus();
    }
    
    // Clear any session data from the server
    fetch('/clear-history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        clear_session: true,
        session_id: sessionStorage.getItem('session_id') || '' 
      })
    }).catch(error => console.error('Error clearing session:', error));
    
    console.log("Chat reset to initial state");
  };

  /**
   * Handle clicks on suggestion elements - using event delegation
   * @param {Event} event - Click event
   */
  const handleSuggestionClick = (event) => {
    // Find the closest suggestion element (supports clicking on child elements)
    const suggestion = event.target.closest('.suggestion');
    if (!suggestion) return;
    
    const suggestionText = suggestion.textContent.trim();
    if (suggestionText) {
      sendMessage(suggestionText);
    }
  };

  /**
   * Attach click listeners to all suggestion elements
   * Uses event delegation for better performance and to handle dynamic elements
   */
  const attachSuggestionListeners = () => {
    // Remove old event delegation if exists
    if (elements.suggestions) {
      // Use event delegation instead of attaching to each element
      elements.suggestions.addEventListener('click', handleSuggestionClick);
      console.log("Attached suggestion listeners via delegation");
    } else {
      console.error("Suggestions container not found");
    }
  };

  /**
   * Debounce function to limit function call frequency
   * @param {Function} func - Function to debounce
   * @param {number} wait - Wait time in ms
   * @returns {Function} Debounced function
   */
  const debounce = (func, wait) => {
    let timeout;
    return function(...args) {
      const context = this; // Preserve 'this' context
      const later = () => {
        clearTimeout(timeout);
        func.apply(context, args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  };

  /**
   * Auto-resize text input field based on content
   */
  const resizeInput = function() {
    // 'this' should be the input element
    if (!this || !this.style) {
      console.error("Invalid context for resizeInput");
      return;
    }
    
    this.style.maxHeight = "none";
    this.style.height = 'auto';
    this.style.height = `${this.scrollHeight}px`;
    
    // Toggle classes based on typing state
    if (this.value.trim() !== '') {
      if (elements.initialView) elements.initialView.classList.add('typing');
      if (elements.suggestions) elements.suggestions.classList.add('typing');
    } else {
      if (elements.initialView) elements.initialView.classList.remove('typing');
      if (elements.suggestions) elements.suggestions.classList.remove('typing');
    }
  };

  // Create properly debounced resize function that maintains context
  const debouncedResizeInput = debounce(resizeInput, CONFIG.typingInterval);

  /**
   * Initialize all event listeners
   */
  const initEventListeners = () => {
    // Input submit event handling
    if (elements.userInput) {
      elements.userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          const message = elements.userInput.value.trim();
          if (message) {
            sendMessage(message);
            elements.userInput.value = '';
            elements.userInput.style.height = '';
          }
        }
      });
      
      // Auto-resize as user types
      elements.userInput.addEventListener('input', debounce(resizeInput, CONFIG.typingInterval));
    }
    
    // Send button click
    if (elements.sendBtn) {
      elements.sendBtn.addEventListener('click', () => {
        const message = elements.userInput.value.trim();
        if (message) {
          sendMessage(message);
          elements.userInput.value = '';
          elements.userInput.style.height = '';
        }
      });
    }
    
    // Attach suggestion click listeners
    attachSuggestionListeners();
    
    // New chat icon - reset chat state
    if (elements.newChatIcon) {
      elements.newChatIcon.addEventListener('click', () => {
        console.log("New chat icon clicked");
        resetChat();
      });
    }
    
    // Focus input field on page load
    setTimeout(() => {
      if (elements.userInput) {
        elements.userInput.focus();
      }
    }, 1000);
  };

  /**
   * Initialize or retrieve session ID
   * Ensures we have a persistent session ID for the conversation
   */
  const initSession = () => {
    // Check if we already have a session ID in storage
    let sessionId = sessionStorage.getItem('session_id');
    
    // If no session ID exists, create a new one
    if (!sessionId) {
      // Generate a simple UUID v4
      sessionId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
      });
      
      // Save it to session storage
      sessionStorage.setItem('session_id', sessionId);
      console.log("New session initialized:", sessionId);
    } else {
      console.log("Existing session retrieved:", sessionId);
    }
    
    return sessionId;
  };

  // Start the application by initializing event listeners
  initSession();
  initEventListeners();
  console.log("Kachifo chat interface initialized");
}