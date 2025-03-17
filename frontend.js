fetch('/api/data')
    .then(response => response.json())
    .then(data => console.log(data));
