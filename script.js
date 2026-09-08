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
    imagem: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQAAAABAAABBKADAAQAAAABAAAA0QAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/8AAEQgA0QEEAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMAAgICAgICBAICBAUEBAQFBwUFBQUHCQcHBwcHCQsJCQkJCQkLCwsLCwsLCw0NDQ0NDQ8PDw8PEREREREREREREf/bAEMBAwMDBAQEBwQEBxIMCgwSEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEhISEv/dAAQAEf/aAAwDAQACEQMRAD8A/fyiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//Q/fyiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi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4up2xr+Vnxi16Tw2dZvbd0juGuriO3LkAb9ztnkEbgqkqDwxAXqa/aLWNFufD0ghmbfDLkRS9MkDJUjs2ATjuOR0OPyR8V+D5fGninU9Bi06TU3a7uQIIomlkG5nQlQgLKcEjK4PPBr8z8Q6cY0sGnFyXO9FrfTY+p4erKVapUqaaK/3nj9zNpOr20avdXVxI0McskdqzDzI2aPLLjC4zwSnzY3AHdmnwaTe2Gmx23gu2gshuSQtchiWRj8ygMC4OAPvgYGFx/d+0/B/7I/xW15RJeW1vo0B2nddyDewxjiOPe2QB0fbX1B4R/Yw8B6UUn8XXt1q0i53Rp/o0DZ9VQtJx7SD6V8fgeGM6xatSw/JD++7L/wFWb+5ntYjPMHR05r+mv8AwD8s7PRbm8tTpmrSnUHmygAQJksAAFVecgjK4ORnrXufgP8AZb+JWsW8EGi6E2nW0SiOOa+/cBV/7aZlYHqSFOa/XTwv4B8F+CoRD4V0u1sfkCF4YwJHUf35Pvv9WJrrsCvrsD4bwt/woYlyX8sfdX/B+5Hh1+Jqj0owt6nwZ4T/AGI9PiKT+NtYkmIwWt7BAi8dvNk3Eg/7imvprwp8DfhX4NVW0fRrZpQoUz3C+fIcd90m7aT324/ICvWaK+zy7hvKsBb6rh0mur1f3u7PDr5hia/8Sbt26fcIABwKWiivcOMKKKKACiiigAooooAKKKKACiiigD//0v38ooooAKKKKACiiigAooooAKKKKACiiigAooooArXlnbX9s9ndqHjkG1lPHH1HIPoRyD0qtpejaRokBttHtobWNmLssKBAzHqxwBknuTya0qKVle4BRRRTAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9P9/KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9T9/KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9k=",
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
