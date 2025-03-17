const express = require('express');
const app = express();

app.use(express.json());

app.post('/add', (req, res) => {
  const { a, b } = req.body;
  const result = a + b;
  res.json({ result });
});

app.listen(3000, () => {
  console.log('Server is running on port 3000');
});
