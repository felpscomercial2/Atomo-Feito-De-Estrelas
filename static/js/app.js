// ============================================================
// ÁTOMO — APP PRINCIPAL
// ============================================================

const API = 'https://horus-production.up.railway.app';
let currentUser = null;
let widgets = [];
let notificacoes = [];
let filtrosAtuais = {};
let metas = [];
let conquistas = [];

// ============================================================
// INICIALIZAÇÃO
// ============================================================

document.addEventListener('DOMContentLoaded', function() {
  iniciarApp();
});

function iniciarApp() {
  carregarUsuario();
  carregarNotificacoes();
  carregarTheme();
  carregarMetas();
  configurarAtalhosTeclado();
  marcarPaginaAtiva();
}

// ============================================================
// USUÁRIO
// ============================================================

function carregarUsuario() {
  const email = localStorage.getItem('horus_user_email');
  if (email) {
    currentUser = email;
    const footer = document.getElementById('footerInfo');
    if (footer) footer.textContent = '👤 ' + email;
  }
}

function logout() {
  localStorage.removeItem('horus_user_email');
  localStorage.removeItem('horus_filtros');
  localStorage.removeItem('atomo_logged_in');
  localStorage.removeItem('atomo_theme');
  window.location.href = '/index.html';
}

// ============================================================
// PÁGINA ATIVA NA SIDEBAR
// ============================================================

function marcarPaginaAtiva() {
  const current = window.location.pathname;
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.remove('active');
    if (item.getAttribute('href') === current) {
      item.classList.add('active');
    }
  });
}

// ============================================================
// FILTROS
// ============================================================

function carregarFiltros() {
  const saved = localStorage.getItem('horus_filtros');
  if (saved) {
    filtrosAtuais = JSON.parse(saved);
  }
  
  // Carrega opções dos selects
  fetch(`${API}/api/filtros`)
    .then(res => res.json())
    .then(data => {
      const selects = {
        filtroAno: data.anos || [],
        filtroUnidade: data.unidades || [],
        filtroMarca: data.marcas || [],
        filtroVendedor: data.vendedores || []
      };
      
      Object.entries(selects).forEach(([id, options]) => {
        const select = document.getElementById(id);
        if (!select) return;
        select.innerHTML = '<option value="">Todos</option>';
        options.forEach(opt => {
          const option = document.createElement('option');
          option.value = opt;
          option.textContent = opt;
          const key = id.replace('filtro', '').toLowerCase();
          if (filtrosAtuais[key] === opt) {
            option.selected = true;
          }
          select.appendChild(option);
        });
      });
      
      aplicarFiltros();
    })
    .catch(err => console.error('Erro ao carregar filtros:', err));
}

function aplicarFiltros() {
  const filtros = {
    ano: document.getElementById('filtroAno')?.value || '',
    mes: document.getElementById('filtroMes')?.value || '',
    unidade: document.getElementById('filtroUnidade')?.value || '',
    marca: document.getElementById('filtroMarca')?.value || '',
    vendedor: document.getElementById('filtroVendedor')?.value || ''
  };
  
  filtrosAtuais = filtros;
  localStorage.setItem('horus_filtros', JSON.stringify(filtros));
  atualizarTagsFiltros(filtros);
  
  // Dispara evento para as páginas recarregarem
  document.dispatchEvent(new CustomEvent('filtrosAplicados', { detail: filtros }));
}

function atualizarTagsFiltros(filtros) {
  const container = document.getElementById('filtrosAtivos');
  if (!container) return;
  
  const tags = [];
  const meses = ['','Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  
  Object.entries(filtros).forEach(([key, value]) => {
    if (value) {
      const label = {
        ano: `Ano: ${value}`,
        mes: `Mês: ${meses[value] || value}`,
        unidade: `Unidade: ${value}`,
        marca: `Marca: ${value}`,
        vendedor: `Vendedor: ${value}`
      }[key];
      if (label) {
        tags.push(`<div class="filtro-tag">${label} <button onclick="removerFiltro('${key}')">×</button></div>`);
      }
    }
  });
  
  container.innerHTML = tags.length ? tags.join('') : '';
}

function removerFiltro(key) {
  const el = document.getElementById(`filtro${key.charAt(0).toUpperCase() + key.slice(1)}`);
  if (el) el.value = '';
  aplicarFiltros();
}

function getFiltros() {
  return filtrosAtuais;
}

function montarParams(filtros) {
  const params = new URLSearchParams();
  Object.entries(filtros).forEach(([key, value]) => {
    if (value) params.append(key, value);
  });
  return params.toString();
}

// ============================================================
// NOTIFICAÇÕES
// ============================================================

function carregarNotificacoes() {
  const saved = localStorage.getItem('atomo_notifications');
  if (saved) {
    notificacoes = JSON.parse(saved);
  }
  atualizarBadgeNotificacoes();
}

function adicionarNotificacao(mensagem, tipo = 'info', icone = 'ℹ️') {
  notificacoes.unshift({
    id: Date.now(),
    mensagem,
    tipo,
    icone,
    lida: false,
    data: new Date().toISOString()
  });
  
  if (notificacoes.length > 50) notificacoes.pop();
  localStorage.setItem('atomo_notifications', JSON.stringify(notificacoes));
  atualizarBadgeNotificacoes();
  mostrarToast(mensagem, tipo, icone);
}

function mostrarToast(mensagem, tipo = 'info', icone = 'ℹ️') {
  const container = document.getElementById('notificationContainer');
  if (!container) return;
  
  const toast = document.createElement('div');
  toast.className = `notification notification-${tipo}`;
  toast.innerHTML = `
    <span class="notification-icon">${icone}</span>
    <span>${mensagem}</span>
    <button class="notification-close" onclick="this.parentElement.remove()">✕</button>
  `;
  
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    setTimeout(() => toast.remove(), 300);
  }, 5000);
}

function atualizarBadgeNotificacoes() {
  const naoLidas = notificacoes.filter(n => !n.lida).length;
  const badge = document.getElementById('notifBadge');
  if (badge) {
    badge.textContent = naoLidas;
    badge.style.display = naoLidas > 0 ? 'inline' : 'none';
  }
}

function abrirNotificacoes() {
  const naoLidas = notificacoes.filter(n => !n.lida);
  naoLidas.forEach(n => n.lida = true);
  localStorage.setItem('atomo_notifications', JSON.stringify(notificacoes));
  atualizarBadgeNotificacoes();
  
  if (notificacoes.length === 0) {
    mostrarToast('📭 Nenhuma notificação', 'info', '📭');
    return;
  }
  
  const lista = notificacoes.slice(0, 10).map(n => `
    <div class="notification notification-${n.tipo}" style="margin-bottom:4px;">
      <span class="notification-icon">${n.icone}</span>
      <span>${n.mensagem}</span>
      <span style="font-size:10px;color:var(--muted);margin-left:auto">${new Date(n.data).toLocaleDateString()}</span>
    </div>
  `).join('');
  
  const container = document.getElementById('notificationContainer');
  if (!container) return;
  
  const panel = document.createElement('div');
  panel.className = 'notification notification-info';
  panel.style.maxWidth = '400px';
  panel.innerHTML = `
    <span class="notification-icon">📋</span>
    <div style="flex:1;max-height:300px;overflow-y:auto;">
      <div style="font-weight:700;margin-bottom:8px;">📋 Notificações</div>
      ${lista}
    </div>
    <button class="notification-close" onclick="this.parentElement.remove()">✕</button>
  `;
  
  container.appendChild(panel);
}

// ============================================================
// EXPORTAÇÕES
// ============================================================

function exportarPDF() {
  adicionarNotificacao('📄 Gerando PDF...', 'info', '📄');
  
  const scripts = [
    'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js'
  ];
  
  let loaded = 0;
  scripts.forEach(src => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = () => {
      loaded++;
      if (loaded === scripts.length) {
        gerarPDF();
      }
    };
    document.head.appendChild(script);
  });
  
  function gerarPDF() {
    const element = document.querySelector('.main-content') || document.querySelector('.main');
    if (!element) {
      adicionarNotificacao('❌ Elemento não encontrado para gerar PDF', 'danger', '❌');
      return;
    }
    
    html2canvas(element, { scale: 2, useCORS: true }).then(canvas => {
      const imgData = canvas.toDataURL('image/png');
      const pdf = new jspdf.jsPDF('l', 'mm', 'a4');
      const imgWidth = 297;
      const imgHeight = (canvas.height * imgWidth) / canvas.width;
      pdf.addImage(imgData, 'PNG', 0, 0, imgWidth, imgHeight);
      pdf.save('relatorio_atomo.pdf');
      adicionarNotificacao('✅ PDF gerado com sucesso!', 'success', '✅');
    }).catch(err => {
      adicionarNotificacao('❌ Erro ao gerar PDF: ' + err.message, 'danger', '❌');
    });
  }
}

function exportarExcel() {
  adicionarNotificacao('📊 Gerando Excel...', 'info', '📊');
  const params = montarParams(filtrosAtuais);
  window.location.href = `${API}/api/exportar?${params}`;
  setTimeout(() => {
    adicionarNotificacao('✅ Excel gerado com sucesso!', 'success', '✅');
  }, 2000);
}

function compartilharFiltros() {
  const params = new URLSearchParams(filtrosAtuais);
  const url = window.location.origin + window.location.pathname + '?' + params.toString();
  
  if (navigator.clipboard) {
    navigator.clipboard.writeText(url)
      .then(() => adicionarNotificacao('🔗 Link copiado!', 'success', '🔗'))
      .catch(() => {
        prompt('Copie o link:', url);
      });
  } else {
    prompt('Copie o link:', url);
  }
}

// ============================================================
// ATALHOS DE TECLADO
// ============================================================

function configurarAtalhosTeclado() {
  document.addEventListener('keydown', function(e) {
    // Ctrl+K = Abrir Valter
    if (e.ctrlKey && e.key === 'k') {
      e.preventDefault();
      toggleValter();
    }
    
    // Escape = Fechar Valter
    if (e.key === 'Escape') {
      const panel = document.getElementById('iaPanel');
      if (panel && panel.classList.contains('open')) {
        toggleValter();
      }
    }
    
    // Alt + número = navegação
    if (e.altKey) {
      const pages = {
        '1': '/home.html',
        '2': '/visao-geral.html',
        '3': '/vendedor.html',
        '4': '/regiao.html',
        '5': '/marcas.html',
        '6': '/produtos.html',
        '7': '/carteira.html',
        '8': '/shelflife.html'
      };
      if (pages[e.key]) {
        e.preventDefault();
        window.location.href = pages[e.key];
      }
    }
  });
}

// ============================================================
// TEMA (DARK/LIGHT)
// ============================================================

function toggleTheme() {
  const current = document.body.getAttribute('data-theme');
  const newTheme = current === 'dark' ? 'light' : 'dark';
  document.body.setAttribute('data-theme', newTheme);
  localStorage.setItem('atomo_theme', newTheme);
  adicionarNotificacao(`🌓 Tema ${newTheme === 'dark' ? 'escuro' : 'claro'} ativado`, 'info', '🌓');
}

function carregarTheme() {
  const saved = localStorage.getItem('atomo_theme');
  if (saved) {
    document.body.setAttribute('data-theme', saved);
  }
}

// ============================================================
// VALTER (ASSISTENTE IA)
// ============================================================

function toggleValter() {
  const panel = document.getElementById('iaPanel');
  if (!panel) return;
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) {
    document.getElementById('iaInput')?.focus();
  }
}

function enviarPergunta(texto) {
  const input = document.getElementById('iaInput');
  const mensagem = texto || input.value.trim();
  if (!mensagem) return;
  
  const messages = document.getElementById('iaMessages');
  messages.innerHTML += `<div class="ia-msg user"><div class="ia-msg-bubble">${mensagem}</div></div>`;
  if (!texto) input.value = '';
  messages.scrollTop = messages.scrollHeight;
  
  // Mostra indicador de digitação
  messages.innerHTML += `<div class="ia-msg bot" id="iaTyping"><div class="ia-msg-bubble" style="background:var(--bg);">⏳ Pensando...</div></div>`;
  messages.scrollTop = messages.scrollHeight;
  
  // Envia para a API
  const params = montarParams(filtrosAtuais);
  fetch(`${API}/api/valter/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      mensagem: mensagem,
      contexto: window.location.pathname,
      filtros: filtrosAtuais
    })
  })
  .then(res => res.json())
  .then(data => {
    const typing = document.getElementById('iaTyping');
    if (typing) typing.remove();
    
    const resposta = data.resposta || data.content?.[0]?.text || 'Não entendi, tente novamente.';
    messages.innerHTML += `<div class="ia-msg bot"><div class="ia-msg-bubble">${resposta}</div></div>`;
    messages.scrollTop = messages.scrollHeight;
  })
  .catch(err => {
    const typing = document.getElementById('iaTyping');
    if (typing) typing.remove();
    messages.innerHTML += `<div class="ia-msg bot"><div class="ia-msg-bubble" style="color:var(--danger);border-color:var(--danger);">❌ Erro: ${err.message}</div></div>`;
    messages.scrollTop = messages.scrollHeight;
  });
}

// ============================================================
// GAMIFICAÇÃO (Metas)
// ============================================================

function carregarMetas() {
  const saved = localStorage.getItem('atomo_metas');
  if (saved) {
    metas = JSON.parse(saved);
  } else {
    metas = [
      { id: 'meta_faturamento', titulo: '💰 Faturamento', meta: 1000000, progresso: 0, unidade: 'R$' },
      { id: 'meta_clientes', titulo: '👥 Clientes Ativos', meta: 100, progresso: 0, unidade: 'clientes' },
      { id: 'meta_vendas', titulo: '📦 Vendas', meta: 500, progresso: 0, unidade: 'vendas' }
    ];
    localStorage.setItem('atomo_metas', JSON.stringify(metas));
  }
  atualizarBadgeMetas();
}

function atualizarMetas(dados) {
  metas.forEach(meta => {
    if (meta.id === 'meta_faturamento' && dados.faturamento) {
      meta.progresso = dados.faturamento;
    }
    if (meta.id === 'meta_clientes' && dados.total_clientes) {
      meta.progresso = dados.total_clientes;
    }
    if (meta.id === 'meta_vendas' && dados.qtd_vendas) {
      meta.progresso = dados.qtd_vendas;
    }
  });
  localStorage.setItem('atomo_metas', JSON.stringify(metas));
  atualizarBadgeMetas();
  verificarConquistas();
}

function atualizarBadgeMetas() {
  const completas = metas.filter(m => m.progresso >= m.meta).length;
  const badge = document.getElementById('badgeMetas');
  if (badge) {
    badge.textContent = completas;
    badge.style.display = completas > 0 ? 'inline' : 'none';
  }
}

function verificarConquistas() {
  const saved = localStorage.getItem('atomo_conquistas');
  conquistas = saved ? JSON.parse(saved) : [];
  
  const totalMetas = metas.filter(m => m.progresso >= m.meta).length;
  
  if (totalMetas === 3) {
    desbloquearConquista('🌟 Mestre das Metas', 'Todas as metas atingidas!');
  } else if (totalMetas >= 2) {
    desbloquearConquista('⭐ Super Estrela', '2 metas atingidas!');
  } else if (totalMetas >= 1) {
    desbloquearConquista('🎯 Primeira Meta', 'Primeira meta atingida!');
  }
}

function desbloquearConquista(nome, descricao) {
  const existe = conquistas.some(c => c.nome === nome);
  if (!existe) {
    conquistas.push({ nome, descricao, data: new Date().toISOString() });
    localStorage.setItem('atomo_conquistas', JSON.stringify(conquistas));
    adicionarNotificacao(`🏆 Conquista desbloqueada: ${nome}!`, 'success', '🏆');
  }
}

// ============================================================
// UTILITÁRIOS
// ============================================================

function formatarMoeda(valor) {
  if (valor === undefined || valor === null) return 'R$ 0,00';
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL'
  }).format(valor);
}

function formatarNumero(valor) {
  return new Intl.NumberFormat('pt-BR').format(valor || 0);
}

function animarContador(elemento, valorFinal) {
  if (!elemento) return;
  const valorInicial = parseInt(elemento.textContent?.replace(/[^0-9]/g, '') || 0, 10);
  const destino = parseInt(String(valorFinal).replace(/[^0-9]/g, ''), 10) || 0;
  
  if (valorInicial === destino) {
    elemento.textContent = valorFinal;
    return;
  }
  
  const duracao = 500;
  const inicioTempo = performance.now();
  
  function passo(agora) {
    const progresso = Math.min((agora - inicioTempo) / duracao, 1);
    const valorAtual = Math.round(valorInicial + (destino - valorInicial) * progresso);
    elemento.textContent = String(valorFinal).replace(/[0-9]/g, valorAtual);
    if (progresso < 1) requestAnimationFrame(passo);
  }
  requestAnimationFrame(passo);
}

function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

// ============================================================
// EXPORTA FUNÇÕES GLOBAIS
// ============================================================

window.API = API;
window.getFiltros = getFiltros;
window.montarParams = montarParams;
window.aplicarFiltros = aplicarFiltros;
window.removerFiltro = removerFiltro;
window.carregarFiltros = carregarFiltros;
window.carregarMetas = carregarMetas;
window.atualizarMetas = atualizarMetas;
window.toggleTheme = toggleTheme;
window.carregarTheme = carregarTheme;
window.toggleValter = toggleValter;
window.enviarPergunta = enviarPergunta;
window.exportarPDF = exportarPDF;
window.exportarExcel = exportarExcel;
window.compartilharFiltros = compartilharFiltros;
window.abrirNotificacoes = abrirNotificacoes;
window.adicionarNotificacao = adicionarNotificacao;
window.formatarMoeda = formatarMoeda;
window.formatarNumero = formatarNumero;
window.animarContador = animarContador;
window.logout = logout;
