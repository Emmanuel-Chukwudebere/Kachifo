// Constants for configuration and state management
const CONFIG = {
  LOADING_MESSAGES: [
    "AI is fetching trends for you!",
    "Hold tight! We're gathering data...",
    "Did you know: The term 'trending' was popularized by social media?",
    "Did you know? Honey never spoils.",
    "Fact: Bananas are berries, but strawberries aren't!",
    "Fun fact: Octopuses have three hearts.",
    "A group of flamingos is called a 'flamboyance.'",
    "Cats have fewer toes on their back paws.",
    "Sharks existed before trees.",
    "A snail can sleep for three years.",
    "Wombat poop is cube-shaped.",
    "You can't hum while holding your nose closed.",
    "Bees can recognize human faces.",
    "Did you know AI can predict trends 10x faster than humans?",
    "Tip: Try searching for trending news about technology.",
    "Here's a fun fact: The first tweet was posted in 2006 by Twitter's founder.",
    "Hold tight! We're fetching the latest news from the web for you!",
    "Fun fact: The term 'trending' was popularized by social media platforms.",
    "Did you know that over 3.6 billion people use social media worldwide?",
    "Tip: Ask about the latest trends in your favorite topics!",
    "Here's a trivia: The word 'hashtag' was first used in 2007.",
    "Did you know: Google processes over 3.5 billion searches per day?",
    "Fun fact: The first ever online sale was made in 1994."
  ],
  ANIMATION_DURATION: 500,
  LOADING_MESSAGE_INTERVAL: 2000,
  TYPING_DEBOUNCE_DELAY: 100
};

// Cache management using localStorage
const CacheManager = {
  set: (key, value, ttl = 3600000) => { // Default TTL: 1 hour
    const item = {
      value,
      expiry: Date.now() + ttl
    };
    localStorage.setItem(key, JSON.stringify(item));
  },
  
  get: (key) => {
    const item = localStorage.getItem(key);
    if (!item) return null;
    
    const parsedItem = JSON.parse(item);
    if (Date.now() > parsedItem.expiry) {
      localStorage.removeItem(key);
      return null;
    }
    return parsedItem.value;
  },
  
  clear: () => localStorage.clear()
};

// Enhanced message streaming handler
class MessageStreamer {
  constructor(chatWindow) {
    this.chatWindow = chatWindow;
    this.loadingInterval = null;
    this.currentLoadingMessage = null;
    this.isStreaming = false;
  }

  // Start streaming loading messages while waiting for response
  startLoadingMessages(typingBubble) {
    let lastIndex = -1;
    
    this.loadingInterval = setInterval(() => {
      if (!this.isStreaming) {
        let randomIndex;
        do {
          randomIndex = Math.floor(Math.random() * CONFIG.LOADING_MESSAGES.length);
        } while (randomIndex === lastIndex);
        
        lastIndex = randomIndex;
        const message = CONFIG.LOADING_MESSAGES[randomIndex];
        
        this.updateMessageWithAnimation(typingBubble, message);
      }
    }, CONFIG.LOADING_MESSAGE_INTERVAL);
  }

  // Smoothly update message content with fade animation
  updateMessageWithAnimation(container, newContent) {
    const messageElement = document.createElement('p');
    messageElement.textContent = newContent;
    messageElement.style.opacity = '0';
    
    // Remove old message with fade-out if it exists
    if (container.childNodes.length > 0) {
      const oldMessage = container.childNodes[0];
      oldMessage.style.transition = `opacity ${CONFIG.ANIMATION_DURATION}ms ease-out`;
      oldMessage.style.opacity = '0';
      
      setTimeout(() => {
        oldMessage.remove();
        container.appendChild(messageElement);
        
        // Trigger reflow for smooth animation
        messageElement.offsetHeight;
        
        messageElement.style.transition = `opacity ${CONFIG.ANIMATION_DURATION}ms ease-in`;
        messageElement.style.opacity = '1';
      }, CONFIG.ANIMATION_DURATION);
    } else {
      container.appendChild(messageElement);
      setTimeout(() => {
        messageElement.style.transition = `opacity ${CONFIG.ANIMATION_DURATION}ms ease-in`;
        messageElement.style.opacity = '1';
      }, 10);
    }
  }

  // Handle the actual response streaming
  async streamResponse(response, typingBubble) {
    this.isStreaming = true;
    clearInterval(this.loadingInterval);

    try {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim() && line.startsWith('data: ')) {
            const data = line.slice(5);
            try {
              const parsedData = JSON.parse(data);
              this.handleParsedData(parsedData, typingBubble);
            } catch (e) {
              // Handle plain text messages
              this.updateMessageWithAnimation(typingBubble, data);
            }
          }
        }
      }
    } catch (error) {
      console.error('Streaming error:', error);
      this.updateMessageWithAnimation(typingBubble, 'An error occurred while streaming the response.');
    } finally {
      this.isStreaming = false;
    }
  }

  // Handle different types of parsed data
  handleParsedData(data, typingBubble) {
    if (data.error) {
      this.updateMessageWithAnimation(typingBubble, data.error);
    } else if (data.results) {
      const resultsHtml = data.results.map(item => `
        <div class="result-item">
          <h3>${this.escapeHtml(item.title)}</h3>
          <p>${this.escapeHtml(item.summary)}</p>
          <a href="${this.escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">[""]</a>
        </div>
      `).join('');
      
      typingBubble.innerHTML = resultsHtml;
    } else {
      this.updateMessageWithAnimation(typingBubble, JSON.stringify(data));
    }
  }

  // Security: Escape HTML to prevent XSS
  escapeHtml(unsafe) {
    return unsafe
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
  const streamer = new MessageStreamer(document.querySelector('.chat-window'));
  const ui = new ChatUI(streamer);
  ui.initialize();
});

// UI Management Class
class ChatUI {
  constructor(streamer) {
    this.streamer = streamer;
    this.elements = {
      userInput: document.getElementById('user-input'),
      sendBtn: document.getElementById('send-btn'),
      chatWindow: document.querySelector('.chat-window'),
      initialView: document.querySelector('.initial-view'),
      suggestions: document.querySelector('.suggestions'),
      newChatIcon: document.querySelector('.new-chat-icon')
    };
  }

  initialize() {
    this.attachEventListeners();
    this.setupObservers();
    this.scrollToBottom();
  }

  attachEventListeners() {
    // Send button click handler
    this.elements.sendBtn.addEventListener('click', (e) => {
      e.preventDefault();
      this.handleSendMessage();
    });

    // Enter key handler (desktop only)
    this.elements.userInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && window.innerWidth >= 1024) {
        e.preventDefault();
        this.handleSendMessage();
      }
    });

    // Input handler for auto-resize
    this.elements.userInput.addEventListener('input', 
      this.debounce(this.handleInput.bind(this), CONFIG.TYPING_DEBOUNCE_DELAY)
    );

    // New chat handler
    this.elements.newChatIcon.addEventListener('click', (e) => {
      e.preventDefault();
      this.resetChat();
    });

    // Suggestion click handlers
    this.attachSuggestionListeners();
  }

  // Handle sending messages
  async handleSendMessage(message = '') {
    const messageText = message || this.elements.userInput.value.trim();
    if (!messageText) return;

    // Create message bubbles
    this.createUserMessage(messageText);
    const typingBubble = this.createBotMessage(true);

    try {
      const response = await fetch('/interact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: messageText })
      });

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      
      await this.streamer.streamResponse(response, typingBubble);
    } catch (error) {
      console.error('Error:', error);
      this.streamer.updateMessageWithAnimation(
        typingBubble, 
        'I apologize, but something went wrong. Please try again.'
      );
    }

    this.elements.userInput.value = '';
    this.elements.userInput.style.height = 'auto';
    this.updateUIState();
  }

  // Helper methods
  createUserMessage(message) {
    const bubble = document.createElement('div');
    bubble.classList.add('user-message');
    bubble.innerHTML = `<div class="message-content">${this.formatMessageWithLinks(message)}</div>`;
    this.elements.chatWindow.appendChild(bubble);
    this.scrollToBottom();
    return bubble;
  }

  createBotMessage(isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add('kachifo-message');
    
    const logo = document.createElement('img');
    logo.src = '/static/logo/kachifo-logo-small.svg';
    logo.alt = 'Kachifo Logo';
    logo.classList.add('kachifo-logo-small');
    
    const content = document.createElement('div');
    content.classList.add('message-content');
    
    if (isTyping) {
      const loadingGif = document.createElement('img');
      loadingGif.src = '/static/icons/typing-gif.gif';
      loadingGif.alt = 'Loading...';
      loadingGif.classList.add('loading-gif');
      content.appendChild(loadingGif);
    }
    
    bubble.appendChild(logo);
    bubble.appendChild(content);
    this.elements.chatWindow.appendChild(bubble);
    this.scrollToBottom();
    
    return content;
  }

  // Utility methods
  formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return message.replace(urlRegex, url => 
      `<a href="${url}" target="_blank" rel="noopener noreferrer">[""]</a>`
    );
  }

  scrollToBottom() {
    this.elements.chatWindow.scrollTop = this.elements.chatWindow.scrollHeight;
  }

  debounce(func, wait) {
    let timeout;
    return (...args) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(this, args), wait);
    };
  }

  // Additional UI state management methods...
  updateUIState() {
    this.elements.initialView.classList.add('hidden');
    this.elements.suggestions.classList.add('hidden');
    this.elements.chatWindow.classList.add('active');
  }

  resetChat() {
    this.elements.chatWindow.innerHTML = '';
    this.elements.initialView.classList.remove('hidden');
    this.elements.suggestions.classList.remove('hidden');
    this.elements.chatWindow.classList.remove('active');
    this.elements.userInput.value = '';
    this.scrollToBottom();
    this.attachSuggestionListeners();
  }

  // Error handling
  setupErrorHandling() {
    window.addEventListener('unhandledrejection', event => {
      console.error('Unhandled promise rejection:', event.reason);
    });

    window.onerror = (message, source, lineno, colno, error) => {
      console.error('Global error:', { message, source, lineno, colno, error });
    };
  }
}