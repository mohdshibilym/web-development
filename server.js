const express = require('express');
const app = express();
const port = 3000;
const host = '0.0.0.0'; // Correctly set

// Dummy data
const users = [
  { id: 1, name: 'Alice in Wonderland', email: 'alice@example.com' },
  { id: 2, name: 'Bob', email: 'bob@example.com' },
  { id: 3, name: 'Charlie', email: 'charlie@example.com' }
];

const products = [
  { id: 1, name: 'Laptop', price: 1000 },
  { id: 2, name: 'Phone', price: 500 },
  { id: 3, name: 'Tablet', price: 300 }
];

// Middleware to parse JSON
app.use(express.json());

// Endpoints
app.get('/users', (req, res) => {
  res.json(users);
});

app.get('/users/:id', (req, res) => {
  const user = users.find(u => u.id === parseInt(req.params.id));
  if (user) {
    res.json(user);
  } else {
    res.status(404).send('User not found');
  }
});

app.get('/products', (req, res) => {
  res.json(products);
});

app.get('/products/:id', (req, res) => {
  const product = products.find(p => p.id === parseInt(req.params.id));
  if (product) {
    res.json(product);
  } else {
    res.status(404).send('Product not found');
  }
});

// Start the server
const server = app.listen(port, () => { // Assign the server instance
  console.log(`[NodeApp] Server is supposed to be running on http://localhost:${port}`);
});

// VERY IMPORTANT: Add error handling for the server instance
server.on('error', (err) => {
  console.error('[NodeApp ERROR] Server failed to start or encountered an error:', err);
  if (err.code === 'EADDRINUSE') {
    console.error(`[NodeApp ERROR] Port ${port} is already in use.`);
  }
  if (err.code === 'EACCES') {
    console.error(`[NodeApp ERROR] Permission denied to use port ${port}.`);
  }
  // Ensure the process exits if the server can't start, making it clearer in Actions
  process.exit(1);
});

// Optional: Handle unhandled promise rejections and uncaught exceptions globally
process.on('unhandledRejection', (reason, promise) => {
  console.error('[NodeApp ERROR] Unhandled Rejection at:', promise, 'reason:', reason);
  process.exit(1); // Exit on unhandled rejection
});

process.on('uncaughtException', (err) => {
  console.error('[NodeApp ERROR] Uncaught Exception:', err);
  process.exit(1); // Exit on uncaught exception
});
