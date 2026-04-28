/* ══════════════════════════════════════════
   BUSINESS INTELLIGENCE — Report Logic
   ══════════════════════════════════════════ */

let rChart = null;
let eChart = null;

function initBusinessReport() {
  console.log("[*] Initializing Business Intelligence Report...");
  
  // Initialize Charts
  setupRevenueChart();
  setupEconChart();
  
  // Initialize Calculator
  setupCalculator();
  
  // Intersection Observer for animations
  const io = new IntersectionObserver(entries => {
    entries.forEach(e => { if(e.isIntersecting){ e.target.classList.add('visible'); io.unobserve(e.target); } });
  }, { threshold: 0.06 });
  document.querySelectorAll('.section').forEach(s => io.observe(s));
  
  // Market bars animation
  const barObs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if(e.isIntersecting){
        e.target.querySelectorAll('[data-width]').forEach(bar => {
          setTimeout(() => { bar.style.width = bar.dataset.width; }, 100);
        });
        barObs.unobserve(e.target);
      }
    });
  }, { threshold: 0.2 });
  const mb = document.getElementById('market-bars');
  if(mb) barObs.observe(mb);
}

function setupRevenueChart() {
  const ctx = document.getElementById('rChart');
  if (!ctx || typeof Chart === 'undefined') {
    console.warn("[!] rChart canvas or Chart.js missing");
    return;
  }
  
  if (rChart) rChart.destroy();
  
  rChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['M1','M2','M3','M4','M5','M6','M7','M8','M9','M10','M11','M12'],
      datasets: [{
        label: 'MRR Growth',
        data: [1200, 2400, 4800, 7200, 10500, 14200, 18500, 24100, 31200, 40500, 52400, 68000],
        borderColor: '#4db6ac',
        backgroundColor: 'rgba(77, 182, 172, 0.1)',
        borderWidth: 2,
        tension: 0.4,
        fill: true
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#999' } },
        x: { grid: { display: false }, ticks: { color: '#999' } }
      }
    }
  });
}

function setupEconChart() {
  const ctx = document.getElementById('eChart');
  if (!ctx || typeof Chart === 'undefined') {
    console.warn("[!] eChart canvas or Chart.js missing");
    return;
  }
  
  if (eChart) eChart.destroy();
  
  eChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Profit', 'Infra', 'Support', 'Sales'],
      datasets: [{
        data: [71, 6, 5, 3],
        backgroundColor: ['#4db6ac', '#ef5350', '#ffb74d', '#9575cd'],
        borderWidth: 0,
        hoverOffset: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '75%',
      plugins: { legend: { display: false } }
    }
  });
}

function setupCalculator() {
  const slC = document.getElementById('sl-c');
  const slK = document.getElementById('sl-k');
  const slA = document.getElementById('sl-a');
  const slE = document.getElementById('sl-e');

  if (!slC || !slK || !slA || !slE) {
    console.warn("[!] Calculator sliders missing");
    return;
  }

  const update = () => {
    const clients = parseInt(slC.value);
    const camsPerClient = parseInt(slK.value);
    const advShare = parseInt(slA.value) / 100;
    const entShare = parseInt(slE.value) / 100;
    const stdShare = Math.max(0, 1 - advShare - entShare);

    const oc = document.getElementById('oc');
    const ok = document.getElementById('ok');
    const oa = document.getElementById('oa');
    const oe = document.getElementById('oe');
    
    if (oc) oc.textContent = clients;
    if (ok) ok.textContent = camsPerClient;
    if (oa) oa.textContent = (advShare * 100).toFixed(0) + '%';
    if (oe) oe.textContent = (entShare * 100).toFixed(0) + '%';

    const totalCams = clients * camsPerClient;
    const mrr = totalCams * (stdShare * 45 + advShare * 85 + entShare * 150);
    const arr = mrr * 12;
    const gp = arr * 0.835;

    const omrr = document.getElementById('o-mrr');
    const otc = document.getElementById('o-tc');
    const oarr = document.getElementById('o-arr');
    const oar = document.getElementById('o-ar');
    const ogp = document.getElementById('o-gp');

    if (omrr) omrr.textContent = '$' + Math.round(mrr).toLocaleString();
    if (otc) otc.textContent = totalCams.toLocaleString() + ' active cameras';
    if (oarr) oarr.textContent = '$' + Math.round(arr).toLocaleString();
    if (oar) oar.textContent = '$' + Math.round(mrr / (totalCams || 1)) + ' avg rate';
    if (ogp) ogp.textContent = '$' + Math.round(gp).toLocaleString();

    // Update chart data points
    if (rChart && typeof Chart !== 'undefined') {
      const newData = [];
      for(let i=1; i<=12; i++) {
        newData.push((mrr / 12) * i * (1 + (i*0.05))); 
      }
      rChart.data.datasets[0].data = newData;
      rChart.update('none');
    }
  };

  [slC, slK, slA, slE].forEach(el => {
    el.addEventListener('input', update);
  });
  
  update();
}
