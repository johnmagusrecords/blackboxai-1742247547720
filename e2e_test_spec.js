describe('My Application', () => {
    it('Should load the home page', () => {
        cy.visit('/');
        cy.contains('Welcome to my app');
    });
});
