def get_dashboard_template():

        return """<!DOCTYPE html>
        <html>
        <head>
            <title>Advanced Trading Bot v2.1</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background: #f8f9fa;
                }
                .container {
                    max-width: 1600px;
                    margin: 0 auto;
                }
                .header {
                    text-align: center;
                    color: #333;
                    margin-bottom: 30px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    border-radius: 10px;
                }
                .connection-status {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    padding: 8px 16px;
                    border-radius: 20px;
                    font-size: 12px;
                    font-weight: bold;
                    z-index: 1000;
                    transition: all 0.3s ease;
                }
                .connection-status.connected {
                    background: #28a745;
                    color: white;
                }
                .connection-status.disconnected {
                    background: #dc3545;
                    color: white;
                }
                .connection-status.connecting {
                    background: #ffc107;
                    color: #212529;
                }
                .notifications {
                    position: fixed;
                    top: 20px;
                    left: 20px;
                    width: 300px;
                    z-index: 1001;
                }
                .notification {
                    background: white;
                    border-radius: 8px;
                    padding: 12px 16px;
                    margin-bottom: 10px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                    border-left: 4px solid #007bff;
                    transform: translateX(-100%);
                    transition: all 0.3s ease;
                }
                .notification.show {
                    transform: translateX(0);
                }
                .notification.info { border-left-color: #007bff; }
                .notification.success { border-left-color: #28a745; }
                .notification.warning { border-left-color: #ffc107; }
                .notification.error { border-left-color: #dc3545; }
                .notification-title {
                    font-weight: bold;
                    margin-bottom: 4px;
                }
                .notification-message {
                    font-size: 14px;
                    color: #666;
                }
                .card {
                    background: white;
                    border-radius: 10px;
                    padding: 25px;
                    margin: 20px 0;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                }
                .stats {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 20px;
                }
                .stat-item {
                    text-align: center;
                    padding: 20px;
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    border-radius: 10px;
                    color: white;
                }
                .stat-value {
                    font-size: 28px;
                    font-weight: bold;
                }
                .stat-label {
                    color: #f8f9fa;
                    margin-top: 8px;
                    font-size: 14px;
                }
                .positive {
                    color: #28a745;
                }
                .negative {
                    color: #dc3545;
                }
                .neutral {
                    color: #6c757d;
                }
                .table {
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 15px;
                }
                .table th, .table td {
                    padding: 12px 8px;
                    text-align: left;
                    border-bottom: 1px solid #dee2e6;
                }
                .table th {
                    background: #f8f9fa;
                    font-weight: 600;
                    color: #495057;
                }
                .table tr:hover {
                    background: #f8f9fa;
                }
                .btn {
                    padding: 10px 20px;
                    border: none;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    margin: 3px;
                    transition: all 0.3s;
                }
                .btn-primary {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }
                .btn-danger {
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    color: white;
                }
                .btn-success {
                    background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
                    color: white;
                }
                .btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                }
                .btn-balance {
                    background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
                    color: white;
                    margin: 3px;
                    padding: 8px 15px;
                    font-size: 13px;
                }
                .btn-balance:hover {
                    transform: translateY(-1px);
                    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                }
                .config-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                }
                .config-item {
                    margin-bottom: 15px;
                }
                .config-item label {
                    display: block;
                    margin-bottom: 5px;
                    font-weight: 600;
                    color: #495057;
                    font-size: 13px;
                }
                .config-item input, .config-item select {
                    width: 100%;
                    padding: 8px;
                    border: 2px solid #e9ecef;
                    border-radius: 4px;
                    font-size: 13px;
                    transition: border-color 0.3s;
                }
                .config-item input:focus, .config-item select:focus {
                    border-color: #667eea;
                    outline: none;
                    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
                }
                .demo-mode {
                    background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
                    color: #8b4513;
                    padding: 15px;
                    border-radius: 10px;
                    margin-bottom: 20px;
                    text-align: center;
                    font-weight: 600;
                }
                .status-badge {
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-weight: 600;
                }
                .status-open {
                    background: #e3f2fd;
                    color: #1976d2;
                }
                .status-tp1 {
                    background: #e8f5e8;
                    color: #2e7d32;
                }
                .status-trailing {
                    background: #fff3e0;
                    color: #f57c00;
                }
                .config-section {
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 8px;
                    margin-bottom: 15px;
                }
                .config-section h4 {
                    margin: 0 0 15px 0;
                    color: #495057;
                    font-size: 16px;
                }
                .position-row-updated {
                    animation: highlight 2s ease-out;
                }
                @keyframes highlight {
                    0% { background-color: rgba(40, 167, 69, 0.2); }
                    100% { background-color: transparent; }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div id="connectionStatus" class="connection-status connecting">
                    Подключение...
                </div>

                <div id="notifications" class="notifications"></div>

                <div class="header">
                <h1>Advanced Trading Bot v2.1 - С WEBSOCKET</h1>
                <p>Real-time обновления | Все настройки в веб-интерфейсе | Исправлен Ctrl+C | Исправлен демо баланс</p>
                <div class="nav-buttons">
                    <a href="/telegram" class="nav-btn">📱 Telegram</a>
                    <a href="/statistics" class="nav-btn">📊 Статистика</a>
                </div>
            </div>


                <div id="demo-mode-alert" class="demo-mode" style="display: none;">
                    Работа в ДЕМО РЕЖИМЕ - Реальные деньги не рискуют
                </div>

                <div class="card">
                    <h3>Системная статистика</h3>
                    <div class="stats" id="stats-container"></div>
                </div>

                <div class="card">
                    <h3>Активные позиции</h3>
                    <div style="overflow-x: auto;">
                        <table class="table" id="positions-table">
                            <thead>
                                <tr>
                                    <th>Символ</th>
                                    <th>Сторона</th>
                                    <th>Вход</th>
                                    <th>Цели</th>
                                    <th>SL</th>
                                    <th>Маржа</th>
                                    <th>PnL</th>
                                    <th>Статус</th>
                                    <th>Действия</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>
                </div>

                <div class="card">
                    <h3>Торговые настройки (ВСЕ ПАРАМЕТРЫ)</h3>
                    <div class="config-grid">
                        <div class="config-section">
                            <h4>Основные настройки</h4>
                            <div class="config-item">
                                <label for="trade_amount">Размер сделки (USDT):</label>
                                <input type="number" id="trade_amount" step="1" min="1">
                            </div>
                            <div class="config-item">
                                <label for="max_positions">Макс. позиций:</label>
                                <input type="number" id="max_positions" step="1" min="1" max="20">
                            </div>
                            <div class="config-item">
                                <label for="leverage">Плечо:</label>
                                <input type="number" id="leverage" step="1" min="1" max="100">
                            </div>
                            <div class="config-item">
                                <label for="margin_mode">Режим маржи:</label>
                                <select id="margin_mode">
                                    <option value="ISOLATED">Изолированная</option>
                                    <option value="CROSS">Кросс-маржа</option>
                                </select>
                            </div>
                            <div class="config-item">
                                <label for="min_balance">Мин. баланс (USDT):</label>
                                <input type="number" id="min_balance" step="1" min="10">
                            </div>
                        </div>

                        <div class="config-section">
                            <h4>Take Profit настройки</h4>
                            <div class="config-item">
                                <label for="tp1_close_percent">Закрыть % на TP1:</label>
                                <input type="number" id="tp1_close_percent" step="0.1" min="0" max="100">
                            </div>
                            <div class="config-item">
                                <label for="trailing_percent">Trailing Stop %:</label>
                                <input type="number" id="trailing_percent" step="0.1" min="0" max="100">
                            </div>
                            <div class="config-item">
                                <label for="trailing_distance">Trailing Distance %:</label>
                                <input type="number" id="trailing_distance" step="0.1" min="0" max="10">
                            </div>
                        </div>

                        <div class="config-section">
                            <h4>Stop Loss настройки</h4>
                            <div class="config-item">
                                <label for="auto_stop_loss">Авто SL:</label>
                                <select id="auto_stop_loss">
                                    <option value="true">Включен</option>
                                    <option value="false">Выключен</option>
                                </select>
                            </div>
                            <div class="config-item">
                                <label for="default_sl_percent">Стандартный SL %:</label>
                                <input type="number" id="default_sl_percent" step="0.1" min="0.1" max="50">
                            </div>
                        </div>

                        <div class="config-section">
                            <h4>Системные настройки</h4>

                            <!-- Уже существующие поля -->
                            <div class="config-item">
                                <label for="demo_mode">Демо режим:</label>
                                <select id="demo_mode">
                                    <option value="true">Включен</option>
                                    <option value="false">Выключен</option>
                                </select>
                            </div>
                            <div class="config-item">
                                <label for="avoid_news_trading">Избегать новости:</label>
                                <select id="avoid_news_trading">
                                    <option value="true">Включен</option>
                                    <option value="false">Выключен</option>
                                </select>
                            </div>
                            <div class="config-item">
                                <label for="monitor_interval">Интервал монитора (сек):</label>
                                <input type="number" id="monitor_interval" step="1" min="1" max="60">
                            </div>
                            <div class="config-item">
                                <label for="price_check_interval">Интервал цены (сек):</label>
                                <input type="number" id="price_check_interval" step="1" min="1" max="60">
                            </div>
                            <div class="config-item">
                                <label for="position_timeout_hours">Таймаут позиции (часы):</label>
                                <input type="number" id="position_timeout_hours" step="1" min="1" max="168">
                            </div>
                            <div class="config-item">
                                <label for="max_price_deviation">Макс. отклонение цены %:</label>
                                <input type="number" id="max_price_deviation" step="0.1" min="0" max="50">
                            </div>
                            <div class="config-item">
                                <label for="min_signal_confidence">Мин. уверенность сигнала:</label>
                                <input type="number" id="min_signal_confidence" step="0.1" min="0" max="1">
                            </div>

                            <!-- Новые поля для глобальных констант -->
                            <div class="config-item">
                                <label for="bingx_api_key">BingX API Key:</label>
                                <input type="text" id="bingx_api_key">
                            </div>
                            <div class="config-item">
                                <label for="bingx_api_secret">BingX API Secret:</label>
                                <input type="text" id="bingx_api_secret">
                            </div>
                            <div class="config-item">
                                <label for="news_api_key">News API Key:</label>
                                <input type="text" id="news_api_key">
                            </div>
                        </div>

                        <div class="config-section">
                            <h4>Управление демо-балансом</h4>
                            <div class="config-item">
                                <label for="demo_balance">Текущий баланс (USDT):</label>
                                <input type="number" id="demo_balance" step="100" min="0" value="1000">
                            </div>
                            <div class="config-item">
                                <button class="btn btn-primary" onclick="updateDemoBalance()" style="margin-top: 10px;">
                                    🔄 Обновить баланс
                                </button>
                                <button class="btn btn-success" onclick="setCommonBalance(1000)" style="margin-top: 10px;">
                                    💰 1000 USDT
                                </button>
                                <button class="btn btn-success" onclick="setCommonBalance(5000)" style="margin-top: 10px;">
                                    💰 5000 USDT
                                </button>
                                <button class="btn btn-success" onclick="setCommonBalance(10000)" style="margin-top: 10px;">
                                    💰 10000 USDT
                                </button>
                            </div>
                        </div>
                    </div>
                    <button class="btn btn-success" onclick="saveConfig()">Сохранить все настройки</button>
                </div>
            </div>

            <script>
                let currentConfig = {};
                let websocket = null;
                let reconnectAttempts = 0;
                const maxReconnectAttempts = 10;

                const container = document.getElementById('channel_ids_container');
                const input = document.getElementById('channel_ids_input');

                function createTag(id) {
                    const tag = document.createElement('span');
                    tag.textContent = id;
                    tag.style.background = '#667eea';
                    tag.style.color = 'white';
                    tag.style.padding = '2px 6px';
                    tag.style.borderRadius = '4px';
                    tag.style.display = 'flex';
                    tag.style.alignItems = 'center';
                    tag.style.gap = '4px';
                    
                    const removeBtn = document.createElement('span');
                    removeBtn.textContent = '×';
                    removeBtn.style.cursor = 'pointer';
                    removeBtn.onclick = () => container.removeChild(tag);
                    
                    tag.appendChild(removeBtn);
                    container.insertBefore(tag, input);
                }

                input.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && input.value.trim() !== '') {
                        createTag(input.value.trim());
                        input.value = '';
                        e.preventDefault();
                    }
                });

                function getChannelIds() {
                    return Array.from(container.querySelectorAll('span')).map(span => span.firstChild.textContent);
                }

                // WebSocket функции
                function initWebSocket() {
                    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                    const wsUrl = `${protocol}//${window.location.host}/ws`;

                    try {
                        websocket = new WebSocket(wsUrl);
                        updateConnectionStatus('connecting');

                        websocket.onopen = function(event) {
                            console.log('WebSocket connected');
                            updateConnectionStatus('connected');
                            reconnectAttempts = 0;

                            // Запрашиваем начальное состояние
                            sendWebSocketMessage({type: 'get_positions'});
                            sendWebSocketMessage({type: 'get_stats'});
                        };

                        websocket.onmessage = function(event) {
                            try {
                                const data = JSON.parse(event.data);
                                handleWebSocketMessage(data);
                            } catch (error) {
                                console.error(
                                    'Error parsing WebSocket message:', error);
                            }
                        };

                        websocket.onclose = function(event) {
                            console.log('WebSocket disconnected:',
                                        event.code, event.reason);
                            updateConnectionStatus('disconnected');

                            // Попытка переподключения
                            if (reconnectAttempts < maxReconnectAttempts) {
                                reconnectAttempts++;
                                setTimeout(() => {
                                    console.log(`Attempting to reconnect... (${reconnectAttempts}/${maxReconnectAttempts})`);
                                    initWebSocket();
                                }, 3000 * reconnectAttempts);
                            }
                        };

                        websocket.onerror = function(error) {
                            console.error('WebSocket error:', error);
                            updateConnectionStatus('disconnected');
                        };

                    } catch (error) {
                        console.error('Failed to create WebSocket:', error);
                        updateConnectionStatus('disconnected');
                        // Fallback to HTTP polling
                        startHttpPolling();
                    }
                }

                function sendWebSocketMessage(message) {
                    if (websocket && websocket.readyState === WebSocket.OPEN) {
                        websocket.send(JSON.stringify(message));
                        return true;
                    }
                    return false;
                }

                function handleWebSocketMessage(data) {
                    switch (data.type) {
                        case 'full_state':
                            if (data.positions) updatePositionsTable(data.positions);
                            if (data.stats) updateStatsDisplay(data.stats);
                            if (data.config) loadConfigFromData(data.config);
                            break;

                        case 'positions_update':
                            updatePositionsTable(data.positions);
                            break;

                        case 'stats_update':
                            updateStatsDisplay(data.stats);
                            break;

                        case 'notification':
                            showNotification(data.title, data.message, data.level || 'info');
                            break;

                        case 'welcome':
                            console.log('Received welcome message:', data);
                            break;

                        case 'pong':
                            // Ping-pong handled automatically
                            break;

                        default:
                            console.log('Unknown WebSocket message type:', data.type);
                    }
                }

                function updateConnectionStatus(status) {
                    const statusElement = document.getElementById('connectionStatus');
                    statusElement.className = `connection-status ${status}`;

                    switch (status) {
                        case 'connected':
                            statusElement.textContent = '🟢 Подключено';
                            break;
                        case 'connecting':
                            statusElement.textContent = '🟡 Подключение...';
                            break;
                        case 'disconnected':
                            statusElement.textContent = '🔴 Отключено';
                            break;
                    }
                }

                function showNotification(title, message, level = 'info') {
                    const notificationsContainer = document.getElementById('notifications');
                    const notification = document.createElement('div');
                    notification.className = `notification ${level}`;

                    notification.innerHTML = `
                        <div class="notification-title">${title}</div>
                        <div class="notification-message">${message}</div>
                    `;

                    notificationsContainer.appendChild(notification);

                    // Анимация появления
                    setTimeout(() => {
                        notification.classList.add('show');
                    }, 100);

                    // Автоудаление через 5 секунд
                    setTimeout(() => {
                        notification.style.transform = 'translateX(-100%)';
                        setTimeout(() => {
                            if (notification.parentNode) {
                                notification.parentNode.removeChild(notification);
                            }
                        }, 300);
                    }, 5000);
                }

                // Fallback HTTP polling если WebSocket недоступен
                let httpPollingInterval;
                function startHttpPolling() {
                    console.log('Starting HTTP polling as fallback');
                    httpPollingInterval = setInterval(() => {
                        Promise.all([
                            fetchData('/api/positions'),
                            fetchData('/api/stats')
                        ]).then(([positions, stats]) => {
                            updatePositionsTable(positions);
                            updateStatsDisplay(stats);
                        }).catch(error => {
                            console.error('HTTP polling error:', error);
                        });
                    }, 3000);
                }

                function stopHttpPolling() {
                    if (httpPollingInterval) {
                        clearInterval(httpPollingInterval);
                        httpPollingInterval = null;
                    }
                }

                // Utility functions
                function formatNumber(num) {
                    return new Intl.NumberFormat('en-US', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 4
                    }).format(num);
                }

                function getPnlClass(pnl) {
                    if (pnl > 0) return 'positive';
                    if (pnl < 0) return 'negative';
                    return 'neutral';
                }

                function getStatusBadge(position) {
                    if (position.tp1_hit && position.trailing_active) {
                        return '<span class="status-badge status-trailing">Trailing</span>';
                    } else if (position.tp1_hit) {
                        return '<span class="status-badge status-tp1">TP1 Hit</span>';
                    } else {
                        return '<span class="status-badge status-open">Open</span>';
                    }
                }

                async function fetchData(url) {
                    try {
                        const response = await fetch(url);
                        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                        return await response.json();
                    } catch (error) {
                        console.error('Fetch error:', error);
                        throw error;
                    }
                }

                function updatePositionsTable(positions) {
                    const tbody = document.querySelector('#positions-table tbody');
                    if (!tbody) return;

                    const currentRows = tbody.querySelectorAll('tr');
                    const currentPositionIds = Array.from(currentRows).map(row => row.dataset.positionId);
                    const newPositionIds = positions.map(pos => pos.id);

                    tbody.innerHTML = positions.map(pos => `
                        <tr data-position-id="${pos.id}" class="${!currentPositionIds.includes(pos.id) ? 'position-row-updated' : ''}">
                            <td>${pos.symbol}</td>
                            <td>${pos.side.toUpperCase()}</td>
                            <td>${formatNumber(pos.entry)}</td>
                            <td>${formatNumber(pos.tp1)}${pos.tp2 ? ' / ' + formatNumber(pos.tp2) : ''}${pos.tp3 ? ' / ' + formatNumber(pos.tp3) : ''}</td>
                            <td>${formatNumber(pos.sl)} ${pos.auto_sl ? '(AUTO)' : ''}</td>
                            <td>${formatNumber(pos.margin)} USDT</td>
                            <td class="${getPnlClass(pos.pnl)}">${formatNumber(pos.pnl)} USDT (${formatNumber(pos.pnl_percent)}%)</td>
                            <td>${getStatusBadge(pos)}</td>
                            <td>
                                <button class="btn btn-danger" onclick="closePosition('${pos.id}')">Закрыть</button>
                            </td>
                        </tr>
                    `).join('');
                }

                function updateStatsDisplay(stats) {
                    const demoAlert = document.getElementById('demo-mode-alert');
                    if (demoAlert) {
                        demoAlert.style.display = stats.demo_mode ? 'block' : 'none';
                    }

                    // Обновляем поле демо-баланса
                    const demoBalanceInput = document.getElementById('demo_balance');
                    if (demoBalanceInput) {
                        demoBalanceInput.value = stats.balance;
                    }

                    const statsContainer = document.getElementById('stats-container');
                    if (statsContainer) {
                        statsContainer.innerHTML = `
                            <div class="stat-item">
                                <div class="stat-value">${stats.open_positions}</div>
                                <div class="stat-label">Открытые позиции</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.closed_positions}</div>
                                <div class="stat-label">Закрытые позиции</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value ${getPnlClass(stats.total_open_pnl)}">${formatNumber(stats.total_open_pnl)} USDT</div>
                                <div class="stat-label">Общий PnL (открытый)</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value ${getPnlClass(stats.total_closed_pnl)}">${formatNumber(stats.total_closed_pnl)} USDT</div>
                                <div class="stat-label">Общий PnL (закрытый)</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${formatNumber(stats.balance)} USDT</div>
                                <div class="stat-label">Баланс</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value ${getPnlClass(stats.daily_pnl)}">${formatNumber(stats.daily_pnl)} USDT</div>
                                <div class="stat-label">Дневной PnL</div>
                            </div>
                        `;
                    }
                }

                function loadConfigFromData(config) {
                    currentConfig = config;
                    Object.keys(config).forEach(key => {
                        const element = document.getElementById(key);
                        if (element) {
                            if (element.type === 'checkbox') {
                                element.checked = Boolean(config[key]);
                            } else if (element.tagName.toLowerCase() === 'select') {
                                element.value = String(config[key]);
                            } else {
                                element.value = config[key];
                            }
                        }
                    });
                }

                async function loadConfig() {
                    try {
                        const config = await fetchData('/api/config');
                        loadConfigFromData(config);
                        console.log('Config loaded successfully:', config);
                    } catch (error) {
                        console.error('Error loading config:', error);
                        showNotification(
                            'Ошибка', 'Ошибка загрузки настроек', 'error');
                    }
                }

                // Функция для установки стандартных значений баланса
                function setCommonBalance(amount) {
                    document.getElementById('demo_balance').value = amount;
                    updateDemoBalance();
                }

                // Основная функция обновления баланса
                async function updateDemoBalance() {
                    const newBalance = parseFloat(document.getElementById('demo_balance').value);

                    if (isNaN(newBalance) || newBalance < 0) {
                        showNotification(
                            'Ошибка', 'Введите корректную сумму баланса', 'error');
                        return;
                    }

                    if (!confirm(`Установить демо-баланс ${newBalance} USDT?`)) return;

                    const button = event?.target || document.querySelector('button[onclick="updateDemoBalance()"]');
                    const originalText = button.textContent;
                    button.textContent = 'Обновляю...';
                    button.disabled = true;

                    try {
                        const response = await fetch('/api/update_balance', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ new_balance: newBalance })
                        });

                        const result = await response.json();

                        if (response.ok) {
                            showNotification('Успех', result.message, 'success');
                            // WebSocket автоматически получит обновление
                        } else {
                            throw new Error(result.detail || result.message || 'Unknown error');
                        }
                    } catch (error) {
                        console.error('Error updating balance:', error);
                        showNotification(
                            'Ошибка', 'Ошибка обновления баланса: ' + error.message, 'error');
                    } finally {
                        button.textContent = originalText;
                        button.disabled = false;
                    }
                }

                async function saveConfig() {
                    try {
                        const configData = {};

                        // Собираем данные из всех полей
                        Object.keys(currentConfig).forEach(key => {
                            const element = document.getElementById(key);
                            if (element) {
                                if (element.type === 'number') {
                                    configData[key] = parseFloat(element.value) || 0;
                                } else if (element.type === 'checkbox') {
                                    configData[key] = element.checked;
                                } else if (element.tagName === 'SELECT') {
                                    if (key === 'auto_stop_loss' || key === 'demo_mode' || key === 'avoid_news_trading') {
                                        configData[key] = element.value === 'true';
                                    } else {
                                        configData[key] = element.value;
                                    }
                                } else {
                                    configData[key] = element.value;
                                }
                            }
                        });

                        const response = await fetch('/api/config', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify(configData)
                        });

                        if (response.ok) {
                            showNotification(
                                'Успех', 'Настройки успешно сохранены!', 'success');
                            currentConfig = { ...configData };
                        } else {
                            const errorData = await response.json();
                            throw new Error(errorData.detail || 'Unknown error');
                        }

                    } catch (error) {
                        console.error('Error saving config:', error);
                        showNotification(
                            'Ошибка', 'Ошибка сохранения настроек: ' + error.message, 'error');
                    }
                }

                async function closePosition(positionId) {
                    if (!confirm('Вы уверены, что хотите закрыть эту позицию?')) return;

                    // Сначала пытаемся через WebSocket
                    if (!sendWebSocketMessage({
                        type: 'close_position',
                        position_id: positionId
                    })) {
                        // Fallback на HTTP API
                        try {
                            const response = await fetch('/api/close_position', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json'
                                },
                                body: JSON.stringify({ position_id: positionId })
                            });

                            if (response.ok) {
                                showNotification(
                                    'Успех', 'Позиция успешно закрыта!', 'success');
                            } else {
                                const errorData = await response.json();
                                throw new Error(errorData.detail || 'Unknown error');
                            }
                        } catch (error) {
                            console.error('Error closing position:', error);
                            showNotification(
                                'Ошибка', 'Ошибка закрытия позиции: ' + error.message, 'error');
                        }
                    }
                }

                // Инициализация при загрузке страницы
                document.addEventListener('DOMContentLoaded', function() {
                    console.log('Page loaded, initializing...');

                    // Инициализируем WebSocket
                    initWebSocket();

                    // Загружаем конфигурацию как fallback
                    loadConfig().catch(console.error);
                });

                // Очистка при закрытии страницы
                window.addEventListener('beforeunload', function() {
                    if (websocket) {
                        websocket.close();
                    }
                    stopHttpPolling();
                });

                // Обработка ошибок
                window.addEventListener('error', function(e) {
                    console.error('Global error:', e.error);
                });

                window.addEventListener('unhandledrejection', function(e) {
                    console.error('Unhandled promise rejection:', e.reason);
                    e.preventDefault();
                });
            </script>
        </body>
        </html>"""

def get_statistics_template():
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Advanced Trading Bot v2.1</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body { font-family: 'Segoe UI', sans-serif; margin: 20px; background: #f8f9fa; }
h2 { color: #333; }
.header { text-align: center; color: #333; margin-bottom: 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; }
.card { background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
table { width: 100%; border-collapse: collapse; margin-top: 10px; }
th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
th { background: #f0f0f0; }
.positive { color: #28a745; }
.negative { color: #dc3545; }
</style>
</head>
<body>
<div class="header">
    <h1>Advanced Trading Bot v2.1 - С WEBSOCKET</h1>
    <p>Real-time обновления | Все настройки в веб-интерфейсе | Исправлен Ctrl+C | Исправлен демо баланс</p>
</div>

<h2>Статистика за последнюю неделю</h2>

<div class="card">
    <h3>Таблица сделок</h3>
    <table id="stats-table">
        <thead>
            <tr>
                <th>Дата</th>
                <th>Канал</th>
                <th>Пара</th>
                <th>Направление</th>
                <th>Итог (USDT/%) </th>
            </tr>
        </thead>
        <tbody></tbody>
    </table>
</div>

<div class="card">
    <h3>Кривая доходности</h3>
    <canvas id="equityChart" height="100"></canvas>
</div>

<div class="card">
    <h3>Топ каналов по винрейту</h3>
    <ol id="top-channels"></ol>
</div>

<script>
async function fetchStats() {
    const resp = await fetch('/api/statistics');
    const data = await resp.json();

    // Таблица
    const tbody = document.querySelector('#stats-table tbody');
    tbody.innerHTML = data.trades.map(trade => 
        `<tr>
            <td>${trade.date}</td>
            <td>${trade.channel}</td>
            <td>${trade.pair}</td>
            <td>${trade.side}</td>
            <td class="${trade.pnl >= 0 ? 'positive' : 'negative'}">${trade.pnl} USDT (${trade.pnl_percent}%)</td>
        </tr>`
    ).join('');

    // График кривой доходности
    const ctx = document.getElementById('equityChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.equity.map(e => e.date),
            datasets: [{
                label: 'Equity',
                data: data.equity.map(e => e.balance),
                borderColor: '#667eea',
                fill: false,
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            }
        }
    });

    // Топ каналов
    const topList = document.getElementById('top-channels');
    topList.innerHTML = data.top_channels.map(ch => `<li>${ch.name} — ${ch.winrate}%</li>`).join('');
}

document.addEventListener('DOMContentLoaded', fetchStats);
</script>
</body>
</html>
"""

def get_telegram_template():
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Telegram Настройки - Advanced Trading Bot</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f8f9fa;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            position: relative;
        }
        .nav-buttons {
            position: absolute;
            top: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
        }
        .nav-btn {
            padding: 8px 16px;
            background: rgba(255, 255, 255, 0.2);
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-size: 14px;
            transition: all 0.3s;
        }
        .nav-btn:hover {
            background: rgba(255, 255, 255, 0.3);
            transform: translateY(-2px);
        }
        .nav-btn.active {
            background: rgba(255, 255, 255, 0.4);
            font-weight: bold;
        }
        .connection-status {
            position: fixed;
            top: 20px;
            left: 20px;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            z-index: 1000;
        }
        .connection-status.connected {
            background: #28a745;
            color: white;
        }
        .connection-status.disconnected {
            background: #dc3545;
            color: white;
        }
        .connection-status.connecting {
            background: #ffc107;
            color: #212529;
        }
        .notifications {
            position: fixed;
            top: 20px;
            right: 20px;
            width: 300px;
            z-index: 1001;
        }
        .notification {
            background: white;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 10px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border-left: 4px solid #007bff;
            transform: translateX(100%);
            transition: all 0.3s ease;
        }
        .notification.show {
            transform: translateX(0);
        }
        .notification.success { border-left-color: #28a745; }
        .notification.error { border-left-color: #dc3545; }
        .notification.info { border-left-color: #007bff; }
        .notification-title {
            font-weight: bold;
            margin-bottom: 4px;
        }
        .notification-message {
            font-size: 14px;
            color: #666;
        }
        .card {
            background: white;
            border-radius: 10px;
            padding: 25px;
            margin: 20px 0;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        .card h2 {
            margin-top: 0;
            color: #333;
            font-size: 20px;
            margin-bottom: 20px;
            border-bottom: 2px solid #f0f0f0;
            padding-bottom: 10px;
        }
        .config-item {
            margin-bottom: 20px;
        }
        .config-item label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #495057;
            font-size: 14px;
        }
        .config-item input, .config-item select {
            width: 100%;
            padding: 10px;
            border: 2px solid #e9ecef;
            border-radius: 6px;
            font-size: 14px;
            transition: border-color 0.3s;
            box-sizing: border-box;
        }
        .config-item input:focus, .config-item select:focus {
            border-color: #667eea;
            outline: none;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        .config-item input[type="number"] {
            -moz-appearance: textfield;
        }
        .config-item input[type="number"]::-webkit-outer-spin-button,
        .config-item input[type="number"]::-webkit-inner-spin-button {
            -webkit-appearance: none;
            margin: 0;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .btn-success {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }
        .channel-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            border: 2px solid #e9ecef;
            padding: 8px;
            border-radius: 6px;
            min-height: 40px;
            margin-bottom: 10px;
        }
        .channel-tag {
            background: #667eea;
            color: white;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 13px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .channel-tag .remove {
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
        }
        .channel-tag .remove:hover {
            color: #ff4444;
        }
        .channel-input {
            width: 100%;
            padding: 8px;
            border: 2px solid #e9ecef;
            border-radius: 6px;
            font-size: 14px;
            margin-bottom: 10px;
            box-sizing: border-box;
        }
        .channel-help {
            font-size: 12px;
            color: #6c757d;
            margin-top: 5px;
        }
        .verification-section {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }
        .two-column {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 10px;
        }
        .status-badge.connected {
            background: #d4edda;
            color: #155724;
        }
        .status-badge.disconnected {
            background: #f8d7da;
            color: #721c24;
        }
    </style>
</head>
<body>
    <div class="container">
        <div id="connectionStatus" class="connection-status connecting">
            Подключение...
        </div>

        <div id="notifications" class="notifications"></div>

        <div class="header">
            <h1>Telegram Настройки</h1>
            <p>Управление подключением к Telegram и каналами</p>
            <div class="nav-buttons">
                <a href="/" class="nav-btn">🏠 Главная</a>
                <a href="/statistics" class="nav-btn">📊 Статистика</a>
            </div>
        </div>

        <!-- Основные настройки Telegram -->
        <div class="card">
            <h2>🔑 Основные настройки Telegram</h2>
            
            <div class="config-item">
                <label for="api_id">Telegram API ID:</label>
                <input type="number" id="api_id" step="1" min="0" placeholder="Введите API ID">
            </div>

            <div class="config-item">
                <label for="api_hash">Telegram API HASH:</label>
                <input type="text" id="api_hash" placeholder="Введите API Hash">
            </div>

            <div class="config-item">
                <label for="phone">Телефон для входа:</label>
                <input type="text" id="phone" placeholder="+1234567890">
            </div>

            <!-- Секция верификации -->
            <div class="verification-section">
                <h3 style="margin-top: 0;">📱 Верификация</h3>
                
                <!-- Кнопка отправки кода -->
                <div class="config-item">
                    <button class="btn btn-primary" onclick="sendCode()" style="width: 100%;" id="sendCodeBtn">
                        📨 Отправить код подтверждения
                    </button>
                </div>

                <!-- Поля для ввода кода и пароля -->
                <div class="two-column">
                    <div class="config-item">
                        <label for="code">Код подтверждения:</label>
                        <input type="text" id="code" placeholder="Введите код из Telegram" maxlength="6">
                    </div>

                    <div class="config-item">
                        <label for="password">Пароль (2FA, если включен):</label>
                        <input type="password" id="password" placeholder="Введите пароль">
                    </div>
                </div>

                <!-- Кнопка подтверждения -->
                <div class="config-item">
                    <button class="btn btn-success" onclick="verifyCode()" style="width: 100%;" id="verifyBtn">
                        ✅ Подтвердить вход
                    </button>
                </div>

                <!-- Статус подключения -->
                <div style="margin-top: 15px; padding: 10px; background: white; border-radius: 6px;">
                    <span>Статус Telegram: </span>
                    <span id="telegramStatus" class="status-badge disconnected">Не подключен</span>
                </div>
            </div>
        </div>

        <!-- Настройки каналов -->
        <div class="card">
            <h2>📢 Мониторинг каналов</h2>
            
            <div class="config-item">
                <label>ID каналов для мониторинга:</label>
                <div class="channel-tags" id="channelTags"></div>
                <input type="text" id="channelInput" class="channel-input" placeholder="Введите ID канала и нажмите Enter" maxlength="50">
                <div class="channel-help">
                    💡 Введите ID канала (например: -1001234567890) и нажмите Enter. 
                    Можно добавить несколько каналов.
                </div>
            </div>

            <!-- Кнопка сохранения -->
            <div style="display: flex; gap: 10px; margin-top: 20px;">
                <button class="btn btn-primary" onclick="saveTelegramConfig()" style="flex: 1;">
                    💾 Сохранить настройки
                </button>
                <button class="btn btn-success" onclick="testTelegramConnection()" style="flex: 1;">
                    🔌 Проверить подключение
                </button>
            </div>
        </div>
    </div>

    <script>
        let currentConfig = {};
        let websocket = null;
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 10;

        // WebSocket функции
        function initWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws`;

            try {
                websocket = new WebSocket(wsUrl);
                updateConnectionStatus('connecting');

                websocket.onopen = function() {
                    console.log('WebSocket connected');
                    updateConnectionStatus('connected');
                    reconnectAttempts = 0;
                    loadConfig();
                };

                websocket.onmessage = function(event) {
                    try {
                        const data = JSON.parse(event.data);
                        handleWebSocketMessage(data);
                    } catch (error) {
                        console.error('Error parsing WebSocket message:', error);
                    }
                };

                websocket.onclose = function() {
                    console.log('WebSocket disconnected');
                    updateConnectionStatus('disconnected');

                    if (reconnectAttempts < maxReconnectAttempts) {
                        reconnectAttempts++;
                        setTimeout(() => {
                            console.log(`Attempting to reconnect... (${reconnectAttempts}/${maxReconnectAttempts})`);
                            initWebSocket();
                        }, 3000 * reconnectAttempts);
                    }
                };

                websocket.onerror = function(error) {
                    console.error('WebSocket error:', error);
                    updateConnectionStatus('disconnected');
                };

            } catch (error) {
                console.error('Failed to create WebSocket:', error);
                updateConnectionStatus('disconnected');
            }
        }

        function sendWebSocketMessage(message) {
            if (websocket && websocket.readyState === WebSocket.OPEN) {
                websocket.send(JSON.stringify(message));
                return true;
            }
            return false;
        }

        function handleWebSocketMessage(data) {
            switch (data.type) {
                case 'config_update':
                    loadConfigFromData(data.config);
                    break;
                case 'notification':
                    showNotification(data.title, data.message, data.level || 'info');
                    break;
                case 'telegram_status':
                    updateTelegramStatus(data.connected, data.message);
                    break;
            }
        }

        function updateConnectionStatus(status) {
            const statusElement = document.getElementById('connectionStatus');
            statusElement.className = `connection-status ${status}`;

            switch (status) {
                case 'connected':
                    statusElement.textContent = '🟢 Подключено к серверу';
                    break;
                case 'connecting':
                    statusElement.textContent = '🟡 Подключение к серверу...';
                    break;
                case 'disconnected':
                    statusElement.textContent = '🔴 Отключено от сервера';
                    break;
            }
        }

        function updateTelegramStatus(connected, message = '') {
            const statusElement = document.getElementById('telegramStatus');
            if (connected) {
                statusElement.className = 'status-badge connected';
                statusElement.textContent = '✅ Подключен';
            } else {
                statusElement.className = 'status-badge disconnected';
                statusElement.textContent = message || '❌ Не подключен';
            }
        }

        function showNotification(title, message, level = 'info') {
            const notificationsContainer = document.getElementById('notifications');
            const notification = document.createElement('div');
            notification.className = `notification ${level}`;

            notification.innerHTML = `
                <div class="notification-title">${title}</div>
                <div class="notification-message">${message}</div>
            `;

            notificationsContainer.appendChild(notification);

            setTimeout(() => {
                notification.classList.add('show');
            }, 100);

            setTimeout(() => {
                notification.style.transform = 'translateX(100%)';
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.parentNode.removeChild(notification);
                    }
                }, 300);
            }, 5000);
        }

        // Управление тегами каналов
        const channelInput = document.getElementById('channelInput');
        const channelTags = document.getElementById('channelTags');

        function addChannelTag(channelId) {
            if (!channelId || channelId.trim() === '') return;
            
            // Проверяем, существует ли уже такой тег
            const existingTags = Array.from(channelTags.children);
            if (existingTags.some(tag => tag.textContent.includes(channelId))) {
                showNotification('Внимание', 'Этот канал уже добавлен', 'info');
                return;
            }

            const tag = document.createElement('span');
            tag.className = 'channel-tag';
            tag.innerHTML = `
                ${channelId}
                <span class="remove" onclick="this.parentElement.remove()">×</span>
            `;
            channelTags.appendChild(tag);
        }

        channelInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && this.value.trim() !== '') {
                addChannelTag(this.value.trim());
                this.value = '';
                e.preventDefault();
            }
        });

        function getChannelIds() {
            return Array.from(channelTags.children).map(tag => 
                tag.textContent.replace('×', '').trim()
            );
        }

        // Основные функции
        async function loadConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                loadConfigFromData(config);
            } catch (error) {
                console.error('Error loading config:', error);
                showNotification('Ошибка', 'Не удалось загрузить настройки', 'error');
            }
        }

        function loadConfigFromData(config) {
            currentConfig = config;
            
            // Заполняем поля
            const fields = ['api_id', 'api_hash', 'phone'];
            fields.forEach(field => {
                const element = document.getElementById(field);
                if (element && config[field] !== undefined) {
                    element.value = config[field];
                }
            });

            // Заполняем теги каналов
            if (config.channel_ids && Array.isArray(config.channel_ids)) {
                channelTags.innerHTML = '';
                config.channel_ids.forEach(channelId => {
                    addChannelTag(channelId);
                });
            }
        }

        async function sendCode() {
            const api_id = document.getElementById('api_id').value;
            const api_hash = document.getElementById('api_hash').value;
            const phone = document.getElementById('phone').value;

            if (!api_id || !api_hash || !phone) {
                showNotification('Ошибка', 'Заполните все поля Telegram', 'error');
                return;
            }

            const btn = document.getElementById('sendCodeBtn');
            const originalText = btn.textContent;
            btn.textContent = 'Отправка...';
            btn.disabled = true;

            try {
                const response = await fetch('/api/telegram/send_code', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        api_id: parseInt(api_id),
                        api_hash: api_hash,
                        phone: phone
                    })
                });

                const result = await response.json();

                if (response.ok) {
                    showNotification('Успех', 'Код отправлен! Проверьте Telegram', 'success');
                } else {
                    throw new Error(result.detail || 'Ошибка отправки кода');
                }
            } catch (error) {
                console.error('Error sending code:', error);
                showNotification('Ошибка', error.message, 'error');
            } finally {
                btn.textContent = originalText;
                btn.disabled = false;
            }
        }

        async function verifyCode() {
            const code = document.getElementById('code').value;
            const password = document.getElementById('password').value;
            const phone = document.getElementById('phone').value;

            if (!code) {
                showNotification('Ошибка', 'Введите код подтверждения', 'error');
                return;
            }

            const btn = document.getElementById('verifyBtn');
            const originalText = btn.textContent;
            btn.textContent = 'Подтверждение...';
            btn.disabled = true;

            try {
                const response = await fetch('/api/telegram/verify', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        phone: phone,
                        code: code,
                        password: password || null
                    })
                });

                const result = await response.json();

                if (response.ok) {
                    showNotification('Успех', 'Вход выполнен успешно!', 'success');
                    updateTelegramStatus(true);
                } else {
                    throw new Error(result.detail || 'Ошибка верификации');
                }
            } catch (error) {
                console.error('Error verifying code:', error);
                showNotification('Ошибка', error.message, 'error');
                updateTelegramStatus(false, error.message);
            } finally {
                btn.textContent = originalText;
                btn.disabled = false;
            }
        }

        async function saveTelegramConfig() {
            const configData = {
                api_id: parseInt(document.getElementById('api_id').value) || 0,
                api_hash: document.getElementById('api_hash').value,
                phone: document.getElementById('phone').value,
                channel_ids: getChannelIds()
            };

            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(configData)
                });

                if (response.ok) {
                    showNotification('Успех', 'Настройки Telegram сохранены!', 'success');
                } else {
                    const error = await response.json();
                    throw new Error(error.detail || 'Ошибка сохранения');
                }
            } catch (error) {
                console.error('Error saving config:', error);
                showNotification('Ошибка', error.message, 'error');
            }
        }

        async function testTelegramConnection() {
            try {
                const response = await fetch('/api/telegram/status');
                const data = await response.json();
                
                if (data.connected) {
                    showNotification('Успех', 'Подключение к Telegram активно', 'success');
                    updateTelegramStatus(true);
                } else {
                    showNotification('Внимание', 'Telegram не подключен', 'info');
                    updateTelegramStatus(false, 'Не подключен');
                }
            } catch (error) {
                console.error('Error testing connection:', error);
                showNotification('Ошибка', 'Не удалось проверить подключение', 'error');
            }
        }

        // Инициализация
        document.addEventListener('DOMContentLoaded', function() {
            initWebSocket();
        });

        window.addEventListener('beforeunload', function() {
            if (websocket) {
                websocket.close();
            }
        });
    </script>
</body>
</html>"""