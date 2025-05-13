const express = require('express');
const app = express();
const port = 3000;
const host = '0.0.0.0'; // <--- ADD THIS LINE

// Dummy data
const users = [
  { id: 1, name: 'Alice', email: 'alice@example.com' },
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

// Get all users
app.get('/users', (req, res) => {
  res.json(users);
});

// Get a user by ID
app.get('/users/:id', (req, res) => {
  const user = users.find(u => u.id === parseInt(req.params.id));
  if (user) {
    res.json(user);
  } else {
    res.status(404).send('User not found');
  }
});

// Get all products
app.get('/products', (req, res) => {
  res.json(products);
});

// Get a product by ID
app.get('/products/:id', (req, res) => {
  const product = products.find(p => p.id === parseInt(req.params.id));
  if (product) {
    res.json(product);
  } else {
    res.status(404).send('Product not found');
  }
});

// Start the server
app.listen(port, host, () => { // <--- MODIFY THIS LINE to include 'host'
  console.log(`Server is running on http://${host}:${port}`); // You can also update the log message
});
