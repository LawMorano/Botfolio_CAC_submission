(() => {
  const selector = document.getElementById('dimension-unit');
  if (!selector) return;

  const inputs = [...document.querySelectorAll('.design-dimensions input')];
  let previousUnit = selector.value;

  function updateFields(convertValues = false) {
    const unit = selector.value;
    const factor = unit === 'mm' ? 25.4 : 1 / 25.4;

    if (convertValues && unit !== previousUnit) {
      for (const input of inputs) {
        if (input.value !== '') {
          input.value = String(Math.round(Number(input.value) * factor * 100) / 100);
        }
      }
    }

    document.querySelectorAll('.dimension-unit-label').forEach((label) => {
      label.textContent = unit;
    });
    inputs.forEach((input, index) => {
      input.max = unit === 'mm' ? '25400' : '1000';
      input.placeholder = unit === 'mm' ? (index === 2 ? '355.6' : '457.2') : (index === 2 ? '14' : '18');
    });
    previousUnit = unit;
  }

  selector.addEventListener('change', () => updateFields(true));
  updateFields();
})();
