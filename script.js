// ==============================================
// ⚙️ CONFIGURAÇÕES — SUAS INFORMAÇÕES JÁ PREENCHIDAS!
// ==============================================
const CONFIG = {
  chavePix: "junioqg2@gmail.com",
  nomeRecebedor: "Fênix Importes",
  whatsapp: "5521990422420",
  freteFixo: 25.00,
  fretePorEstado: {
    SP: 25.00, RJ: 25.00, MG: 25.00, DF: 25.00, OUTROS: 25.00
  }
};

// ==============================================
// 🛒 CATÁLOGO DE PRODUTOS — PREÇOS DE REVENDA CONFIRMADOS!
// ==============================================
const produtos = [
  // === 💦 WATER BARIOSTATIC VIAL ===
  {
    id: 1,
    nome: "💦 WATER BARIOSTATIC VIAL 2ML",
    preco: 40.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 2,
    nome: "💦 WATER BARIOSTATIC VIAL 3ML",
    preco: 60.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 3,
    nome: "💦 WATER BARIOSTATIC VIAL 10ML",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },

  // === ❤️ TIRZEPATIDA PY ===
  {
    id: 4,
    nome: "❤️ TIRZEDRAL 4X 15 MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 5,
    nome: "❤️ T36 MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 6,
    nome: "🟠 TG 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 7,
    nome: "🟠 TG 5MG",
    preco: 420.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 8,
    nome: "🟡 TIRZEC MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 9,
    nome: "🟡 TIRZEC 4x 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 10,
    nome: "💜 LIPOLESS MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 11,
    nome: "💜 LIPOLESS 4X 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "https://mxeacxvjopeefvqrahby.supabase.co/storage/v1/object/public/produtos/prod-1788822939567-yk3mf4.jpg",
    tag: "Disponível"
  },
  {
    id: 12,
    nome: "⚫ LIPOLAND MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 13,
    nome: "⚫ LIPOLAND 4X 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 14,
    nome: "💙 SLIMEX MD 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 15,
    nome: "🟤 GLUCONEX 4X 15MG",
    preco: 1000.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  },
  {
    id: 16,
    nome: "🟤 GLUCONEX 4X SER 2.5MG 💉",
    preco: 457.00,
    categoria: "perda-peso",
    imagem: "COLOQUE_LINK_DA_FOTO_AQUI",
    tag: "Disponível"
  }
];

// ==============================================
// 🛒 NÃO PRECISA MEXER DAQUI PARA BAIXO 🛒
// ==============================================
let carrinho = [];
let valorFrete = 0;
let estadoSelecionado = "";

document.addEventListener("DOMContentLoaded", () => {
  renderizarProdutos(produtos);
});

function renderizarProdutos(lista) {
  const grid = document.getElementById("produtos-grid");
  grid.innerHTML = lista.map(p => `
    <div class="produto-card">
      <div class="produto-img-wrap">
        ${p.tag ? `<span class="produto-tag">${p.tag}</span>` : ''}
        <img src="${p.imagem}" alt="${p.nome}" class="produto-img">
      </div>
      <div class="produto-info">
        <h3 class="produto-nome">${p.nome}</h3>
        <p class="produto-preco">R$ ${p.preco.toFixed(2).replace('.', ',')}</p>
        <button class="produto-btn" onclick="adicionarAoCarrinho(${p.id})">
          <i class="fas fa-shopping-cart"></i> Encomendar
        </button>
      </div>
    </div>
  `).join("");
}

function filtrarCategoria(cat) {
  document.querySelectorAll(".categoria-item").forEach(el => {
    el.classList.remove("active");
    if (el.dataset.cat === cat) el.classList.add("active");
  });
  const filtrados = cat === "todos" ? produtos : produtos.filter(p => p.categoria === cat);
  renderizarProdutos(filtrados);
}

function adicionarAoCarrinho(id) {
  const prod = produtos.find(p => p.id === id);
  carrinho.push({ ...prod });
  atualizarContadorCarrinho();
  alert(`✅ ${prod.nome} adicionado ao carrinho!`);
}

function removerDoCarrinho(index) {
  carrinho.splice(index, 1);
  atualizarContadorCarrinho();
  renderizarCarrinho();
  atualizarResumo();
}

function atualizarContadorCarrinho() {
  document.getElementById("cart-count").textContent = carrinho.length;
}

function abrirCarrinho() {
  if (carrinho.length === 0) {
    alert("Seu carrinho está vazio!");
    return;
  }
  renderizarCarrinho();
  document.getElementById("modal-carrinho").classList.remove("oculto");
}

function fecharCarrinho() {
  document.getElementById("modal-carrinho").classList.add("oculto");
}

function renderizarCarrinho() {
  const container = document.getElementById("carrinho-itens");
  container.innerHTML = carrinho.map((item, i) => `
    <div class="carrinho-item">
      <span>${item.nome}</span>
      <div>
        <span>R$ ${item.preco.toFixed(2).replace('.', ',')}</span>
        <button onclick="removerDoCarrinho(${i})"> ✕</button>
      </div>
    </div>
  `).join("");
  const subtotal = carrinho.reduce((s, i) => s + i.preco, 0);
  document.getElementById("carrinho-subtotal").textContent = subtotal.toFixed(2).replace('.', ',');
  document.getElementById("carrinho-total-valor").textContent = (subtotal + valorFrete).toFixed(2).replace('.', ',');
}

function calcularFreteCarrinho() {
  const cep = document.getElementById("cep-frete").value.replace(/\D/g, "");
  if (cep.length === 8) {
    valorFrete = CONFIG.freteFixo;
    document.getElementById("frete-valor").textContent = `Frete: R$ ${valorFrete.toFixed(2).replace('.', ',')}`;
    renderizarCarrinho();
  }
}

function abrirFormulario() {
  fecharCarrinho();
  calcularFretePorEstado();
  atualizarResumo();
  document.getElementById("modal-finalizar").classList.remove("oculto");
}

function fecharModal() {
  document.getElementById("modal-finalizar").classList.add("oculto");
  document.getElementById("passo-dados").classList.remove("oculto");
  document.getElementById("passo-pagamento").classList.add("oculto");
}

function buscarCep() {
  const cep = document.getElementById("cep").value.replace(/\D/g, "");
  if (cep.length === 8) alert("✅ CEP encontrado! Preencha os demais dados.");
}

function calcularFretePorEstado() {
  estadoSelecionado = document.getElementById("estado").value;
  valorFrete = CONFIG.fretePorEstado[estadoSelecionado] || CONFIG.fretePorEstado.OUTROS;
}

function atualizarResumo() {
  const subtotal = carrinho.reduce((s, i) => s + i.preco, 0);
  const total = subtotal + valorFrete;
  document.getElementById("resumo-produtos").textContent = `R$ ${subtotal.toFixed(2).replace('.', ',')}`;
  document.getElementById("resumo-frete").textContent = `R$ ${valorFrete.toFixed(2).replace('.', ',')}`;
  document.getElementById("resumo-total").textContent = `R$ ${total.toFixed(2).replace('.', ',')}`;
  document.getElementById("valor-pix").textContent = total.toFixed(2).replace('.', ',');
  document.getElementById("chave-pix-exibicao").textContent = CONFIG.chavePix;
  gerarCodigoPix(total);
  atualizarLinkWhatsApp(total);
}

function irParaPagamento() {
  const campos = ["nome", "cpf", "celular", "email", "cep", "estado", "cidade", "bairro", "endereco", "numero", "termos"];
  for (const id of campos) {
    const el = document.getElementById(id);
    if (!el.value || (el.type === "checkbox" && !el.checked)) {
      alert("⚠️ Preencha todos os campos obrigatórios!");
      el.focus();
      return;
    }
  }
  calcularFretePorEstado();
  atualizarResumo();
  document.getElementById("passo-dados").classList.add("oculto");
  document.getElementById("passo-pagamento").classList.remove("oculto");
  document.querySelector(".passo").textContent = "2 de 2 - Pagamento";
}

function voltarParaDados() {
  document.getElementById("passo-pagamento").classList.add("oculto");
  document.getElementById("passo-dados").classList.remove("oculto");
  document.querySelector(".passo").textContent = "1 de 2 - Dados";
}

function gerarCodigoPix(valorTotal) {
  const codigoSimulado = `${CONFIG.chavePix}|valor:${valorTotal.toFixed(2)}|nome:${CONFIG.nomeRecebedor}`;
  document.getElementById("codigo-pix").value = codigoSimulado;
}

function copiarCodigoPix() {
  const input = document.getElementById("codigo-pix");
  input.select();
  document.execCommand("copy");
  alert("✅ Código copiado! Abra o app do seu banco e cole.");
}

function atualizarLinkWhatsApp(valorTotal) {
  const texto = `🛒 PEDIDO - Fênix Importes\n\nProdutos:\n${carrinho.map(i => `- ${i.nome}: R$ ${i.preco.toFixed(2)}`).join("\n")}\n\nFrete: R$ ${valorFrete.toFixed(2)}\nTOTAL: R$ ${valorTotal.toFixed(2).replace('.', ',')}\n\nDados:\nNome: ${document.getElementById("nome").value}\nCPF: ${document.getElementById("cpf").value}\nEndereço: ${document.getElementById("endereco").value}, ${document.getElementById("numero").value} - ${document.getElementById("bairro").value}/${document.getElementById("cidade").value}-${document.getElementById("estado").value}\n\n✅ Paguei via Pix! Segue comprovante 👇`;
  document.getElementById("link-whatsapp").href = `https://wa.me/${CONFIG.whatsapp}?text=${encodeURIComponent(texto)}`;
}
